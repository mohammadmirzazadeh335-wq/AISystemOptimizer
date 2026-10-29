"""Attachments: real copies on disk, real extraction, honest gaps.

Every file used here is written by the test itself, so nothing depends on the
machine's documents folder.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.services import attachments as att
from myai.services.attachments import AttachmentService
from myai.services.chat import ChatService
from myai.services.openrouter import ModelInfo, OpenRouterClient

KEY = "sk-or-v1-test"


@pytest.fixture()
def service(ctx) -> AttachmentService:  # noqa: ANN001
    return ctx.attachments


def write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


# ------------------------------------------------------------------ extraction
def test_text_file_is_copied_and_extracted(service: AttachmentService, tmp_path: Path) -> None:
    source = write(tmp_path, "notes.md", "# Plan\n\nShip it.\n")
    record = service.ingest(source)
    assert record.kind == "text"
    assert "# Plan" in record.text
    assert record.chars == len(record.text)
    stored = Path(record.path)
    assert stored.is_file() and stored.parent == service.root
    assert stored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    source.unlink()  # the copy keeps working after the original is gone
    assert Path(record.path).is_file()


def test_persian_cp1256_file_is_decoded(service: AttachmentService, tmp_path: Path) -> None:
    # Windows-1256 uses the Arabic letters (ي/ك), which older Persian files also do.
    text = "سلام دنيا\nهذا اختبار"
    source = write(tmp_path, "letter.txt", text.encode("cp1256"))
    record = service.ingest(source)
    assert "سلام دنيا" in record.text


def test_utf16_file_with_bom_is_decoded(service: AttachmentService, tmp_path: Path) -> None:
    source = write(tmp_path, "utf16.txt", "متن یونیکد".encode("utf-16"))
    assert record_text(service, source) == "متن یونیکد"


def record_text(service: AttachmentService, source: Path) -> str:
    return service.ingest(source).text.strip()


def test_unknown_extension_is_refused(service: AttachmentService, tmp_path: Path) -> None:
    # ``.iso`` is a supported archive now; an extension nobody claims still is not.
    source = write(tmp_path, "mystery.zzz", b"\x00\x01")
    with pytest.raises(ValidationError) as excinfo:
        service.ingest(source)
    assert excinfo.value.message_key == "attachments.unsupported"


def test_missing_file_is_reported(service: AttachmentService, tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        service.ingest(tmp_path / "nope.txt")


def test_oversized_file_is_refused(service: AttachmentService, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(att, "MAX_FILE_BYTES", 10)
    source = write(tmp_path, "big.txt", "x" * 20)
    with pytest.raises(ValidationError) as excinfo:
        service.ingest(source)
    assert excinfo.value.message_key == "attachments.too_large"


def test_binary_bytes_in_a_text_file_are_not_sent(service: AttachmentService, tmp_path: Path) -> None:
    source = write(tmp_path, "blob.txt", b"abc\x00def")
    record = service.ingest(source)
    assert record.text == ""
    assert record.note == "attachments.binary"


def test_docx_text_is_extracted_with_the_standard_library(service: AttachmentService, tmp_path: Path) -> None:
    source = tmp_path / "brief.docx"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", xml)
    record = service.ingest(source)
    assert record.kind == "office"
    assert "Hello world" in record.text
    assert "Second paragraph" in record.text


def test_xlsx_shared_strings_are_extracted(service: AttachmentService, tmp_path: Path) -> None:
    source = tmp_path / "sheet.xlsx"
    shared = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>Name</t></si><si><t>Amount</t></si></sst>"
    )
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row></sheetData></worksheet>'
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    record = service.ingest(source)
    assert "Name" in record.text and "Amount" in record.text


def test_png_dimensions_are_read_from_the_header(service: AttachmentService, tmp_path: Path) -> None:
    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big") + (360).to_bytes(4, "big")
    source = write(tmp_path, "shot.png", header + b"\x00" * 32)
    record = service.ingest(source)
    assert record.kind == "image"
    assert record.text == ""
    assert record.note == "attachments.image_size|640x360"


def test_pdf_is_recorded_without_fake_text(service: AttachmentService, tmp_path: Path) -> None:
    source = write(tmp_path, "paper.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    record = service.ingest(source)
    assert record.kind == "pdf"
    assert record.text == ""
    assert record.note == "attachments.pdf_no_text"


# -------------------------------------------------------------------- context
def test_context_block_labels_and_fences_the_text(service: AttachmentService, tmp_path: Path) -> None:
    record = service.ingest(write(tmp_path, "code.py", "```python\nprint('x')\n```\n"))
    block = service.context_block([record])
    assert record.name in block
    assert "````" in block  # the fence outgrows the backticks inside the file
    assert "```python" in block


def test_context_block_reports_files_without_text(service: AttachmentService, tmp_path: Path) -> None:
    record = service.ingest(write(tmp_path, "scan.pdf", b"%PDF-1.4\n"))
    block = service.context_block([record])
    assert "No text could be extracted" in block
    assert "attachments.pdf_no_text" in block


def test_context_budget_stops_runaway_files(service: AttachmentService, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(att, "MAX_CHARS_TOTAL", 40)
    big = service.ingest(write(tmp_path, "a.txt", "y" * 200))
    small = service.ingest(write(tmp_path, "b.txt", "z" * 200))
    block = service.context_block([big, small])
    assert "truncated to fit the context" in block
    assert "omitted" in block


def test_meta_round_trip_keeps_the_facts(service: AttachmentService, tmp_path: Path) -> None:
    record = service.ingest(write(tmp_path, "x.md", "hello"))
    restored = att.AttachmentRecord.from_meta(record.to_meta())
    assert restored == att.AttachmentRecord(**{**record.__dict__, "text": ""})


# ------------------------------------------------------------------------- db
def test_rows_are_stored_per_message(ctx, service: AttachmentService, tmp_path: Path) -> None:  # noqa: ANN001
    conversation = ctx.conversations.create("Files", select=False)
    message = ctx.conversations.add_message(conversation.id, "user", "look at this")
    record = service.ingest(write(tmp_path, "a.md", "alpha"))
    service.remember(message.id, [record])
    rows = service.for_message(message.id)
    assert [row.name for row in rows] == ["a.md"]
    assert rows[0].chars == 5
    assert service.count() == 1


def test_deleting_the_conversation_removes_the_rows(ctx, service: AttachmentService, tmp_path: Path) -> None:  # noqa: ANN001
    conversation = ctx.conversations.create("Files", select=False)
    message = ctx.conversations.add_message(conversation.id, "user", "x")
    service.remember(message.id, [service.ingest(write(tmp_path, "b.md", "beta"))])
    ctx.conversations.delete(conversation.id)
    assert service.count() == 0


# ----------------------------------------------------------------------- chat
def sse_text(text: str) -> bytes:
    payload = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}
    return f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()


def test_send_sends_the_file_text_and_keeps_chips(ctx, service: AttachmentService, tmp_path: Path) -> None:  # noqa: ANN001
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=sse_text("read it"), headers={"content-type": "text/event-stream"})

    chat = ChatService(
        db=ctx.db,
        bus=ctx.bus,
        conversations=ctx.conversations,
        settings=ctx.settings,
        memory=ctx.memory,
        persona=ctx.persona,
        attachments=service,
        client_factory=lambda: OpenRouterClient(lambda: KEY, transport=httpx.MockTransport(handler)),
    )
    chat.set_models([ModelInfo(id="test/model", name="Test", context_length=8192)])
    conversation = ctx.conversations.create("Attach", select=False)
    source = write(tmp_path, "spec.md", "The widget must be blue.")
    outcome = chat.send(
        conversation.id,
        "Summarise this",
        model_id="test/model",
        attachments=[{"name": source.name, "path": str(source)}],
    )
    assert outcome.error is None
    messages = captured["payload"]["messages"]
    user_turn = next(item for item in messages if item["role"] == "user")
    assert "The widget must be blue." in user_turn["content"]
    assert "spec.md" in user_turn["content"]
    stored = ctx.conversations.messages(conversation.id)[0]
    assert stored.content == "Summarise this"  # the bubble stays readable
    assert stored.meta["attachments"][0]["name"] == "spec.md"
    assert service.for_message(stored.id)[0].chars > 0


def test_attachment_only_message_is_allowed(ctx, service: AttachmentService, tmp_path: Path) -> None:  # noqa: ANN001
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_text("ok"), headers={"content-type": "text/event-stream"})

    chat = ChatService(
        db=ctx.db, bus=ctx.bus, conversations=ctx.conversations, settings=ctx.settings,
        memory=ctx.memory, persona=ctx.persona, attachments=service,
        client_factory=lambda: OpenRouterClient(lambda: KEY, transport=httpx.MockTransport(handler)),
    )
    chat.set_models([ModelInfo(id="test/model", name="Test", context_length=8192)])
    conversation = ctx.conversations.create("Attach", select=False)
    source = write(tmp_path, "only.md", "just a file")
    outcome = chat.send(conversation.id, "", model_id="test/model", attachments=[{"path": str(source)}])
    assert outcome.error is None
