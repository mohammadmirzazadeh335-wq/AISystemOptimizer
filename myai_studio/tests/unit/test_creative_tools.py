"""The generators a chat model uses to make real files, and the formats chat accepts.

Everything here runs offline: a chart is an SVG string, a PDF comes from Qt's own
writer, an image copy from Qt's codec, an archive from ``zipfile``. The tools are
registered in :mod:`myai.services.tools`, so any OpenAI-compatible model can call
them, and the app never claims a format it cannot read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myai.core.errors import ValidationError
from myai.i18n import tr
from myai.services import creative
from myai.services.attachments import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    VIDEO_EXTENSIONS,
    AttachmentService,
    dialog_filters,
    extension_kind,
)
from myai.services.tools import ToolContext, default_specs, registry


# ------------------------------------------------------------------- formats
def test_chat_accepts_the_formats_a_user_really_attaches() -> None:
    """The composer promised ~120 formats; the validator must not know fewer."""
    assert len(SUPPORTED_EXTENSIONS) >= 120
    for suffix in (".pdf", ".docx", ".odt", ".csv", ".py", ".png", ".heic", ".mp3", ".mp4", ".zip"):
        assert suffix in SUPPORTED_EXTENSIONS, suffix
    assert len(IMAGE_EXTENSIONS) >= 20
    assert len(AUDIO_EXTENSIONS) >= 15
    assert len(VIDEO_EXTENSIONS) >= 15


def test_every_extension_is_classified_once() -> None:
    kinds = {extension_kind(suffix) for suffix in SUPPORTED_EXTENSIONS}
    assert {"text", "office", "image", "pdf", "audio", "video", "archive", "data"} <= kinds
    assert extension_kind(".mp4") == "video"
    assert extension_kind(".flac") == "audio"
    assert extension_kind(".docx") == "office"
    assert extension_kind(".zip") == "archive"


def test_the_file_dialog_and_the_validator_cannot_disagree() -> None:
    patterns = " ".join(pattern for _key, pattern in dialog_filters())
    for suffix in (".docx", ".mp4", ".zip", ".pdf"):
        assert f"*{suffix}" in patterns


# ------------------------------------------------------------------ media meta
def test_an_audio_file_is_measured_not_guessed(tmp_path: Path) -> None:
    import wave

    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)  # exactly one second
    info = creative.probe_media(path)
    assert info.kind == "audio"
    assert info.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert "8" in info.describe()


def test_an_mp4_duration_is_read_from_the_header(tmp_path: Path) -> None:
    """A tiny valid ``ftyp`` + ``mvhd`` box: duration 2 s at timescale 1000."""

    def box(kind: bytes, body: bytes) -> bytes:
        return (len(body) + 8).to_bytes(4, "big") + kind + body

    mvhd_body = (
        b"\x00\x00\x00\x00"          # version + flags
        + b"\x00" * 8                # creation / modification
        + (1000).to_bytes(4, "big")  # timescale
        + (2000).to_bytes(4, "big")  # duration
        + b"\x00" * 80
    )
    path = tmp_path / "clip.mp4"
    path.write_bytes(box(b"ftyp", b"isomisom") + box(b"mvhd", mvhd_body))
    info = creative.probe_media(path)
    assert info.kind == "video"
    assert info.duration_seconds == pytest.approx(2.0)


def test_an_attachment_of_every_family_is_ingested_with_real_metadata(ctx) -> None:  # noqa: ANN001
    service = AttachmentService(ctx.paths, ctx.db)
    wav = ctx.paths.home / "note.wav"
    import wave

    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    record = service.ingest(wav)
    assert record.kind == "audio"
    assert record.note.startswith("attachments.media_meta|")

    archive = ctx.paths.home / "bundle.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("readme.txt", "hello")
    listed = service.ingest(archive)
    assert listed.kind == "archive"
    assert "readme.txt" in listed.text


# -------------------------------------------------------------------- charts
def test_a_chart_is_a_real_svg_with_the_numbers_in_it(tmp_path: Path) -> None:
    target = creative.render_chart(
        kind="bar",
        series=[creative.Series("Revenue", [10, 20, 30])],
        path=tmp_path / "chart",
        title="Numbers",
    )
    text = target.read_text(encoding="utf-8")
    assert target.suffix == ".svg"
    assert text.startswith("<svg")
    assert "Numbers" in text
    assert text.count("<rect") >= 3  # one bar per value plus the background
    # The highest bar must be taller than the lowest: the data is drawn, not copied.
    heights = [float(part.split('"')[0]) for part in text.split('height="')[1:]]
    assert max(heights) > min(heights)


def test_a_pie_chart_divides_a_full_circle(tmp_path: Path) -> None:
    target = creative.render_chart(
        kind="pie",
        series=[creative.Series("A", [1]), creative.Series("B", [1])],
        path=tmp_path / "pie.svg",
    )
    assert target.read_text(encoding="utf-8").count("<path") == 2


def test_a_chart_without_numbers_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as caught:
        creative.render_chart(kind="bar", series=[], path=tmp_path / "x.svg")
    assert caught.value.message_key == "creative.no_data"


# ------------------------------------------------------------------ archives
def test_a_zip_bundle_contains_the_files_it_was_given(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    archive = creative.zip_bundle([first, second], tmp_path / "out.zip")
    import zipfile

    with zipfile.ZipFile(archive) as handle:
        assert sorted(handle.namelist()) == ["a.txt", "b.txt"]


# --------------------------------------------------------------------- tools
def test_the_creative_tools_are_registered_and_described() -> None:
    ids = {spec.id for spec in default_specs()}
    assert {
        "create_chart",
        "export_pdf",
        "resize_image",
        "contact_sheet",
        "zip_files",
        "describe_file",
    } <= ids
    for spec in default_specs():
        if spec.id in ids:
            assert spec.description and spec.parameters.get("type") == "object"


def test_create_chart_writes_into_the_outputs_folder(ctx) -> None:  # noqa: ANN001
    tools = registry()
    result = tools.execute(
        "create_chart",
        {"kind": "line", "title": "Load", "labels": ["a", "b"], "values": [1, 4]},
        ToolContext(settings=ctx.settings, paths=ctx.paths),
        require_confirmation=False,
    )
    assert result.ok
    written = Path(result.data["path"])
    assert written.is_file()
    assert written.parent.name == "generated"
    assert written.suffix == ".svg"


def test_a_tool_without_paths_says_so_instead_of_crashing() -> None:
    tools = registry()
    from myai.services.tools import ToolUnavailable

    with pytest.raises(ToolUnavailable):
        tools.execute(
            "create_chart",
            {"kind": "bar", "values": [1]},
            ToolContext(settings=None),
            require_confirmation=False,
        )


def test_zip_and_describe_need_no_gui(tmp_path: Path) -> None:
    tools = registry()
    file = tmp_path / "note.txt"
    file.write_text("x" * 100, encoding="utf-8")
    context = ToolContext()
    context.paths = type("Paths", (), {"outputs_dir": tmp_path / "out"})()
    described = tools.execute(
        "describe_file", {"path": str(file)}, context, require_confirmation=False
    )
    assert described.ok and described.data["bytes"] == 100
    zipped = tools.execute(
        "zip_files", {"paths": [str(file)]}, context, require_confirmation=False
    )
    assert zipped.ok and Path(zipped.data["path"]).is_file()


def test_the_reason_for_a_missing_generator_is_translatable() -> None:
    assert tr("agent.reason_no_pdf")
    assert tr("agent.reason_no_paths")


# ---------------------------------------------------------------- image parts
def _chat_with(ctx, handler, models):  # noqa: ANN001
    import httpx

    from myai.services.chat import ChatService
    from myai.services.openrouter import OpenRouterClient

    service = ChatService(
        db=ctx.db,
        bus=ctx.bus,
        conversations=ctx.conversations,
        settings=ctx.settings,
        memory=ctx.memory,
        persona=ctx.persona,
        client_factory=lambda: OpenRouterClient(
            lambda: "sk-or-v1-" + "a" * 64,
            transport=httpx.MockTransport(handler),
            timeout=5.0,
        ),
        attachments=ctx.attachments,
    )
    service.set_models(models)
    return service


def test_a_picture_reaches_a_vision_model_as_an_image_part(ctx, tmp_path: Path) -> None:  # noqa: ANN001
    """Images used to be reduced to "attached: photo.png". A vision model can do better."""
    import base64
    import json

    from myai.services.openrouter import ModelInfo

    ctx.settings.update({"ai.provider": "openrouter", "ai.attach_images": True})
    png = tmp_path / "pixel.png"
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    captured: dict = {}

    def handler(request) -> object:  # noqa: ANN001
        import httpx

        captured["body"] = json.loads(request.content)
        body = (
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    service = _chat_with(
        ctx,
        handler,
        [ModelInfo(id="vision/model", name="Vision", context_length=8000, supports_vision=True)],
    )
    conversation = ctx.conversations.create(title="pic", select=False)
    ctx.conversations.set_model(conversation.id, "vision/model")
    service.send(conversation.id, "what is this?", model_id="vision/model",
                 attachments=[{"name": png.name, "path": str(png)}])
    first_user = next(m for m in captured["body"]["messages"] if m["role"] == "user")
    assert isinstance(first_user["content"], list)
    assert any(part.get("type") == "image_url" for part in first_user["content"])


def test_a_text_only_model_does_not_receive_base64(ctx, tmp_path: Path) -> None:  # noqa: ANN001
    import base64
    import json

    from myai.services.openrouter import ModelInfo

    ctx.settings.update({"ai.provider": "openrouter", "ai.attach_images": True})
    png = tmp_path / "pixel.png"
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    captured: dict = {}

    def handler(request) -> object:  # noqa: ANN001
        import httpx

        captured["body"] = json.loads(request.content)
        body = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    service = _chat_with(
        ctx,
        handler,
        [ModelInfo(id="text/model", name="Text", context_length=8000, supports_vision=False)],
    )
    conversation = ctx.conversations.create(title="txt", select=False)
    ctx.conversations.set_model(conversation.id, "text/model")
    service.send(conversation.id, "look", model_id="text/model",
                 attachments=[{"name": png.name, "path": str(png)}])
    first_user = next(m for m in captured["body"]["messages"] if m["role"] == "user")
    assert isinstance(first_user["content"], str)
