"""Web research page (Phase 5).

Honest split:

* **Search** needs a search provider. This build has none, so the field and the
  button are disabled and the reason is printed above them.
* **Read a page** is real. A URL is fetched over HTTP by
  :class:`myai.services.web.WebService`, converted to text, and can be copied or
  saved into the output library as Markdown.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
)

from ...core.errors import AppError
from ...core.timeutil import format_bytes
from ...i18n import tr
from ...services.web import WebPage
from ..theme import runtime
from ..widgets.fields import SearchField
from ..widgets.foundation import Badge
from .page_base import PageShell, ghost_button, hint_label, primary_button, run_async

logger = logging.getLogger(__name__)


class WebPageView(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("web.title", "web.subtitle", icon_name="globe")
        self.context = context
        self.service = context.web
        self._page: WebPage | None = None
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        _search_card, search_layout = self.card("web.search_title", "search")
        row = QHBoxLayout()
        row.setSpacing(runtime.px(8))
        self.search_field = SearchField(tr("web.search_placeholder"))
        self.search_field.setEnabled(False)
        row.addWidget(self.search_field, 1)
        self.search_button = primary_button(tr("web.search"), "search")
        self.search_button.setEnabled(False)
        row.addWidget(self.search_button)
        search_layout.addLayout(row)
        self.search_reason = hint_label(tr("web.search_unavailable"), tone="muted")
        search_layout.addWidget(self.search_reason)

        _read_card, read_layout = self.card("web.read_title", "link")
        input_row = QHBoxLayout()
        input_row.setSpacing(runtime.px(8))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("web.url_placeholder"))
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setAccessibleName(tr("web.url_placeholder"))
        self.url_edit.returnPressed.connect(self.fetch_page)
        input_row.addWidget(self.url_edit, 1)
        self.fetch_button = primary_button(tr("web.fetch"), "download")
        self.fetch_button.setObjectName("WebFetch")
        self.fetch_button.clicked.connect(self.fetch_page)
        input_row.addWidget(self.fetch_button)
        read_layout.addLayout(input_row)
        read_layout.addWidget(hint_label(tr("web.read_hint")))

        self.status_row = QHBoxLayout()
        self.status_row.setSpacing(runtime.px(6))
        self.result_badge = Badge("", "muted")
        self.result_badge.setVisible(False)
        self.status_row.addWidget(self.result_badge)
        self.result_meta = QLabel("")
        self.result_meta.setProperty("role", "faint")
        self.status_row.addWidget(self.result_meta, 1)
        read_layout.addLayout(self.status_row)

        self.title_label = QLabel("")
        self.title_label.setProperty("role", "section")
        self.title_label.setWordWrap(True)
        self.title_label.setVisible(False)
        read_layout.addWidget(self.title_label)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlaceholderText(tr("web.no_result"))
        self.text_view.setMinimumHeight(runtime.px(220))
        self.text_view.setAccessibleName(tr("web.read_title"))
        read_layout.addWidget(self.text_view)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(6))
        actions.addStretch(1)
        self.copy_button = ghost_button(tr("web.copy"), "copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)
        actions.addWidget(self.copy_button)
        self.save_button = ghost_button(tr("web.save"), "download")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        self.note_button = ghost_button(tr("web.save_note"), "library")
        self.note_button.setEnabled(False)
        self.note_button.setToolTip(tr("web.save_note_hint"))
        self.note_button.clicked.connect(self.save_as_note)
        actions.addWidget(self.note_button)
        read_layout.addLayout(actions)

    # ------------------------------------------------------------------- data
    #: Readable text of the last fetch, so it can be kept as a real note.
    _last_text = ""

    def refresh(self) -> None:
        available = self.service.search_available
        self.search_field.setEnabled(available)
        self.search_button.setEnabled(available)
        self.search_reason.setText(
            tr("web.search_ready") if available else tr("web.search_unavailable")
        )
        # Saving is only meaningful once a page has actually been read.
        if hasattr(self, "note_button"):
            self.note_button.setEnabled(bool(self._last_text.strip()))

    def save_as_note(self) -> None:
        """Keep the page that was just read as an Output Studio draft.

        Reading a page and then having no way to keep it was a dead end: the app
        already has a real notes/outputs service, so this writes a Markdown file
        there (title, source URL, then the extracted text) instead of a new store.
        """
        text = self._last_text.strip()
        if not text:
            self.notify.emit(tr("web.nothing_to_save"), "warning")
            return
        title = self.title_label.text().strip() if self.title_label.isVisible() else ""
        source = self.url_edit.text().strip()
        name = f"{title or 'page'}.md"[:80]
        body = f"# {title or source}\n\n> {source}\n\n{text}"
        try:
            entry = self.context.outputs.create(name=name, content=body, language="markdown")
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        except Exception as exc:  # noqa: BLE001 - a write failure must not crash the page
            logger.exception("web_note_failed")
            self.notify.emit(str(exc), "error")
            return
        self.notify.emit(tr("web.saved_note", name=entry.name), "success")

    # ---------------------------------------------------------------- actions
    def fetch_page(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.notify.emit(tr("web.error_empty"), "error")
            self.url_edit.setFocus()
            return
        self.fetch_button.setEnabled(False)
        self.fetch_button.setText(tr("web.fetching"))
        self.text_view.setPlainText("")
        self.result_badge.setVisible(False)
        self.title_label.setVisible(False)
        self.result_meta.setText(tr("web.fetching"))

        run_async(
            self,
            lambda: self.service.fetch(url),
            on_success=self._on_fetched,
            on_error=self._on_failed,
        )

    def _on_fetched(self, result: object) -> None:
        page = result
        self._page = page  # type: ignore[assignment]
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText(tr("web.fetch"))
        self.result_badge.setText(tr("web.fetched"))
        self.result_badge.set_tone("success")
        self.result_badge.setVisible(True)
        self.result_meta.setText(
            tr(
                "web.result_meta",
                status=page.status,  # type: ignore[attr-defined]
                size=format_bytes(page.bytes_received),  # type: ignore[attr-defined]
                ms=page.elapsed_ms,  # type: ignore[attr-defined]
                words=page.words,  # type: ignore[attr-defined]
            )
        )
        self.title_label.setText(page.title or page.final_url)  # type: ignore[attr-defined]
        self.title_label.setToolTip(page.final_url)  # type: ignore[attr-defined]
        self.title_label.setVisible(True)
        self.text_view.setPlainText(page.text)  # type: ignore[attr-defined]
        self._last_text = str(page.text or "")  # type: ignore[attr-defined]
        self.note_button.setEnabled(bool(self._last_text.strip()))
        self.copy_button.setEnabled(bool(page.text))  # type: ignore[attr-defined]
        self.save_button.setEnabled(bool(page.text))  # type: ignore[attr-defined]

    def _on_failed(self, exc: Exception) -> None:
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText(tr("web.fetch"))
        self._page = None
        self.result_meta.setText("")
        self.result_badge.setText(tr("web.failed"))
        self.result_badge.set_tone("danger")
        self.result_badge.setVisible(True)
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        message = exc.message if isinstance(exc, AppError) else type(exc).__name__
        self.notify.emit(tr("web.failed_toast", error=message), "error")

    def _copy(self) -> None:
        if self._page is None:
            return
        QGuiApplication.clipboard().setText(self._page.text)
        self.notify.emit(tr("web.copied"), "success")

    def _save(self) -> None:
        if self._page is None:
            return
        name = (self._page.title or "page").strip()[:80]
        for char in '/\\:*?"<>|':
            name = name.replace(char, "-")
        body = (
            f"# {self._page.title or self._page.final_url}\n\n"
            f"Source: {self._page.final_url}\n"
            f"Fetched: {datetime.now().isoformat(timespec='seconds')}\n\n"
            f"{self._page.text}\n"
        )
        try:
            entry = self.context.outputs.create(f"{name or 'page'}.md", body, kind="markdown")
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.notify.emit(tr("web.saved", name=entry.name), "success")

    # -------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.search_field.set_placeholder(tr("web.search_placeholder"))
        self.search_button.setText(tr("web.search"))
        self.fetch_button.setText(tr("web.fetch"))
        self.url_edit.setPlaceholderText(tr("web.url_placeholder"))
        self.text_view.setPlaceholderText(tr("web.no_result"))
        self.copy_button.setText(tr("web.copy"))
        self.save_button.setText(tr("web.save"))
        self.note_button.setText(tr("web.save_note"))
        self.note_button.setToolTip(tr("web.save_note_hint"))
        self.refresh()
