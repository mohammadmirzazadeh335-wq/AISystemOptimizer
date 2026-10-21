"""Rich text view for assistant output with theme-aware typography."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QSizePolicy, QTextBrowser, QWidget

from ...core.markdown import render_markdown
from ..theme import runtime


class MarkdownView(QTextBrowser):
    def __init__(self, parent: QWidget | None = None, *, text: str = "", selectable: bool = True) -> None:
        super().__init__(parent)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._open_link)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.document().setDocumentMargin(0)
        self._markdown = ""
        self._adjusting = False
        self.document().documentLayout().documentSizeChanged.connect(self._sync_height)
        runtime.signals.changed.connect(self._on_theme_changed)
        if text:
            self.set_markdown(text)

    def set_markdown(self, text: str) -> None:
        self._markdown = text or ""
        self._apply_stylesheet()
        body = render_markdown(self._markdown)
        self.setHtml(f"<html><body>{body}</body></html>")
        self.document().setTextWidth(max(120, self.viewport().width()))
        self._sync_height()

    def markdown(self) -> str:
        return self._markdown

    def _apply_stylesheet(self) -> None:
        c = runtime.theme().color
        family = runtime.manager().font_family if runtime.manager() else "DejaVu Sans"
        mono = runtime.manager().mono_family if runtime.manager() else "DejaVu Sans Mono"
        scale = runtime.scale()
        base = round(13.5 * scale)
        self.document().setDefaultFont(runtime.ui_font(13))
        self.setStyleSheet(f"QTextBrowser {{ background: transparent; color: {c('text')}; }}")
        self.document().setDefaultStyleSheet(
            f"""
            body {{ color: {c('text')}; font-family: '{family}'; font-size: {base}px; }}
            p {{ margin: 0px 0px {round(8 * scale)}px 0px; line-height: 150%; }}
            h1 {{ font-size: {round(21 * scale)}px; margin: {round(10 * scale)}px 0 {round(6 * scale)}px 0; }}
            h2 {{ font-size: {round(18 * scale)}px; margin: {round(10 * scale)}px 0 {round(6 * scale)}px 0; }}
            h3 {{ font-size: {round(16 * scale)}px; margin: {round(8 * scale)}px 0 {round(4 * scale)}px 0; }}
            h4, h5, h6 {{ font-size: {round(14 * scale)}px; margin: {round(6 * scale)}px 0 {round(4 * scale)}px 0; }}
            a {{ color: {c('accent')}; text-decoration: none; }}
            code {{ font-family: '{mono}'; font-size: {round(12 * scale)}px; background-color: {c('surface_3')}; color: {c('text')}; }}
            pre {{ font-family: '{mono}'; font-size: {round(12 * scale)}px; background-color: {c('code_bg')}; color: {c('text')}; margin: {round(6 * scale)}px 0; padding: {round(9 * scale)}px; }}
            blockquote {{ margin: {round(4 * scale)}px 0; padding-left: {round(10 * scale)}px; color: {c('text_muted')}; border-left: 2px solid {c('border_strong')}; }}
            li {{ margin: 0px 0px {round(3 * scale)}px 0px; }}
            hr {{ color: {c('border')}; }}
            th {{ background-color: {c('surface_2')}; color: {c('text')}; font-weight: 600; }}
            td {{ color: {c('text')}; }}
            table {{ border-color: {c('border')}; margin: {round(6 * scale)}px 0; }}
            """
        )

    def _sync_height(self, *_args) -> None:
        if self._adjusting:
            return
        self._adjusting = True
        try:
            width = max(120, self.viewport().width())
            doc = self.document()
            if abs(doc.textWidth() - width) > 1:
                doc.setTextWidth(width)
            height = int(doc.size().height()) + 4
            self.setFixedHeight(max(24, height))
            self.updateGeometry()
        finally:
            self._adjusting = False

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.document().setTextWidth(max(120, self.viewport().width()))
        self._sync_height()

    def _on_theme_changed(self, *_args) -> None:
        if self._markdown:
            self.set_markdown(self._markdown)
        else:
            self._apply_stylesheet()

    def _open_link(self, url) -> None:  # noqa: ANN001
        if url.scheme() in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)
