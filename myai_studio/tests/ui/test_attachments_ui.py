"""Attachment UI: chips, identity, preview and the send path.

The dialogs are the only thing stubbed; everything else is the real widget.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from myai.i18n import tr
from myai.ui.widgets.dialogs import PreviewDialog
from myai.ui.widgets.fields import AttachmentChip
from myai.ui.widgets.foundation import Badge


def pump(ms: int = 30) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)


def make_file(tmp_path: Path, folder: str, name: str, text: str) -> Path:
    root = tmp_path / folder
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def test_duplicate_names_are_distinct(ui, tmp_path: Path) -> None:
    window, _context, _theme = ui
    first = make_file(tmp_path, "a", "main.py", "print('a')\n")
    second = make_file(tmp_path, "b", "main.py", "print('b')\n")
    window.composer._add_attachment(str(first))  # noqa: SLF001 - the real handler
    window.composer._add_attachment(str(second))  # noqa: SLF001
    pump()
    chips = window.composer.findChildren(AttachmentChip)
    assert len(chips) == 2
    window.composer._remove_attachment(str(first))  # noqa: SLF001
    pump()
    remaining = window.composer.findChildren(AttachmentChip)
    assert len(remaining) == 1
    assert window.composer.attachments()[0].path == str(second)


def test_attachment_only_send_is_enabled(ui, tmp_path: Path) -> None:
    window, _context, _theme = ui
    window.composer._add_attachment(str(make_file(tmp_path, "x", "note.md", "hello")))  # noqa: SLF001
    pump()
    assert window.composer.send_button.isEnabled()
    captured: list = []
    window.composer.send_requested.connect(lambda text, items: captured.append((text, items)))
    window.composer._submit()  # noqa: SLF001
    assert captured and captured[0][0] == ""
    assert captured[0][1][0]["name"] == "note.md"


def test_unsupported_file_is_refused_with_a_reason(ui, tmp_path: Path) -> None:
    window, _context, _theme = ui
    bad = tmp_path / "tool.exe"
    bad.write_bytes(b"MZ")
    toasts: list = []
    window.composer.notify.connect(lambda message, tone: toasts.append((message, tone)))
    window.composer._add_attachment(str(bad))  # noqa: SLF001
    pump()
    assert toasts and toasts[0][1] == "error"
    assert window.composer.attachments() == []


def test_oversized_file_is_refused(ui, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _context, _theme = ui
    monkeypatch.setattr("myai.ui.views.composer.MAX_FILE_BYTES", 4)
    file_path = make_file(tmp_path, "x", "big.md", "0123456789")
    toasts: list = []
    window.composer.notify.connect(lambda message, tone: toasts.append((message, tone)))
    window.composer._add_attachment(str(file_path))  # noqa: SLF001
    assert toasts and toasts[0][1] == "error"


def test_preview_dialog_shows_the_extracted_text(ui, tmp_path: Path) -> None:
    window, context, _theme = ui
    source = make_file(tmp_path, "x", "spec.md", "# Spec\n\nBlue button.")
    dialog = PreviewDialog(
        window,
        title="spec.md",
        subtitle=tr("composer.preview_meta", kind="text", size="22 B", chars=20),
        text=context.attachments.ingest(source).text,
    )
    assert "Blue button." in dialog.editor.toPlainText()
    assert dialog.editor.isReadOnly()
    dialog.close()


def test_preview_action_opens_a_real_extraction(ui, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _context, _theme = ui
    source = make_file(tmp_path, "x", "readme.md", "real content")
    captured: dict = {}

    class Stub:
        def __init__(self, parent, **kwargs):  # noqa: ANN001
            captured.update(kwargs)

        def exec(self) -> int:  # noqa: D102
            return 1

    monkeypatch.setattr("myai.ui.main_window.PreviewDialog", Stub)
    window._preview_attachment(str(source))  # noqa: SLF001
    assert "real content" in captured["text"]


def test_preview_of_a_binary_file_reports_instead_of_crashing(ui, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _context, _theme = ui
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    toasts: list = []
    window._show_toast = lambda message, tone: toasts.append((message, tone))  # noqa: SLF001
    window._preview_attachment(str(source))  # noqa: SLF001
    assert toasts and toasts[0][1] == "error"


def test_sent_attachment_chips_survive_in_the_bubble(ui, tmp_path: Path) -> None:
    window, context, _theme = ui
    source = make_file(tmp_path, "x", "data.csv", "a,b\n1,2\n")
    conversation = context.conversations.create("CSV", select=False)
    record = context.attachments.ingest(source)
    context.attachments.remember(
        context.conversations.add_message(
            conversation.id, "user", "look", meta={"attachments": [record.to_meta()]}
        ).id,
        [record],
    )
    window.open_conversation(conversation.id)
    pump(60)
    badges = [badge.text() for badge in window.chat_view.findChildren(Badge)]
    assert "data.csv" in badges
    assert context.attachments.count() == 1
