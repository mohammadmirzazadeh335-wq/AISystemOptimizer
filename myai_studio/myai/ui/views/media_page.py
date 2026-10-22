"""Image Studio and Video Studio (Phase 5).

Neither studio can generate media in this build, and both pages say exactly why
on the surface — no disabled-looking button whose only purpose is decoration, no
fake "generating" state. What *is* real is the library: files that already exist
in ``outputs/images`` or ``outputs/videos`` are listed with their real size and
date and can be opened or deleted.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.errors import AppError
from ...core.timeutil import format_bytes, format_datetime
from ...i18n import current_language, tn, tr
from ...services.media import IMAGE_PROVIDER_NOTE, VIDEO_PROVIDER_NOTE, MediaItem
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.foundation import Badge, ElidedLabel
from .page_base import PageShell, ghost_button, hint_label

logger = logging.getLogger(__name__)

THUMB_W = 168
THUMB_H = 104


class MediaCard(QFrame):
    open_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, item: MediaItem, *, thumbnail: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setProperty("panel", "card")
        self.setFixedWidth(runtime.px(196))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(9), runtime.px(9), runtime.px(9), runtime.px(9))
        layout.setSpacing(runtime.px(6))

        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedHeight(runtime.px(THUMB_H))
        preview.setStyleSheet(
            f"background: {runtime.theme().color('surface_3')}; border-radius: {runtime.px(8)}px;"
        )
        if thumbnail:
            pixmap = QPixmap(str(item.path))
            if not pixmap.isNull():
                preview.setPixmap(
                    pixmap.scaled(
                        QSize(runtime.px(THUMB_W), runtime.px(THUMB_H)),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        if preview.pixmap().isNull():
            preview.setPixmap(runtime.icons().px("video" if not thumbnail else "image", 26, "faint"))
        layout.addWidget(preview)

        name = ElidedLabel(item.name, pixel_size=11, weight=500, tone="text")
        name.setToolTip(item.name)
        layout.addWidget(name)
        meta = QLabel(
            tr(
                "media.size_date",
                size=format_bytes(item.size),
                date=format_datetime(item.modified, current_language()) if item.modified else "—",
            )
        )
        meta.setProperty("role", "faint")
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(4))
        actions.addStretch(1)
        open_button = ghost_button("", "external")
        open_button.setAccessibleName(tr("media.open"))
        open_button.setToolTip(tr("media.open"))
        open_button.clicked.connect(lambda: self.open_requested.emit(self.item))
        actions.addWidget(open_button)
        remove = ghost_button("", "trash")
        remove.setAccessibleName(tr("media.delete"))
        remove.setToolTip(tr("media.delete"))
        remove.clicked.connect(lambda: self.delete_requested.emit(self.item))
        actions.addWidget(remove)
        layout.addLayout(actions)


class MediaPage(PageShell):
    """Shared implementation for the two studios."""

    notify = Signal(str, str)

    KIND = "images"
    ICON = "image"
    TITLE_KEY = "images.title"
    SUBTITLE_KEY = "images.subtitle"
    SECTION_KEY = "images.library_title"
    EMPTY_KEY = "images.empty"
    PROVIDER_NOTE = IMAGE_PROVIDER_NOTE

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__(self.TITLE_KEY, self.SUBTITLE_KEY, icon_name=self.ICON)
        self.context = context
        self.service = context.media
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        _status_card, layout = self.card("images.status_title", self.ICON)
        status = QHBoxLayout()
        status.setSpacing(runtime.px(8))
        self.status_badge = Badge(tr("images.unavailable"), "warning")
        status.addWidget(self.status_badge)
        self.provider_badge = Badge(tr("images.no_provider"), "muted")
        status.addWidget(self.provider_badge)
        status.addStretch(1)
        self.generate_button = ghost_button(tr("images.generate"), "sparkles")
        self.generate_button.setEnabled(False)
        status.addWidget(self.generate_button)
        layout.addLayout(status)

        note = QLabel(tr("images.reason", note=self.PROVIDER_NOTE))
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(hint_label(tr("images.what_would_unlock")))

        _library_card, library_layout = self.card("", "layers")
        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px("layers", 14, "muted"))
        head.addWidget(icon)
        self.library_title = QLabel(tr(self.SECTION_KEY))
        self.library_title.setProperty("role", "section")
        head.addWidget(self.library_title)
        self.count_badge = Badge("", "muted")
        head.addWidget(self.count_badge)
        head.addStretch(1)
        self.refresh_button = ghost_button("", "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        head.addWidget(self.refresh_button)
        library_layout.addLayout(head)

        self.empty = QLabel(tr(self.EMPTY_KEY))
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        library_layout.addWidget(self.empty)

        self.grid_host = QWidget()
        self.grid = QHBoxLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(runtime.px(9))
        self.grid.addStretch(1)
        library_layout.addWidget(self.grid_host)

    # ------------------------------------------------------------------- data
    def items(self) -> list[MediaItem]:
        return self.service.images() if self.KIND == "images" else self.service.videos()

    def refresh(self) -> None:
        items = self.items()
        while self.grid.count() > 1:
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for entry in items:
            card = MediaCard(entry, thumbnail=self.KIND == "images")
            card.open_requested.connect(self._open)
            card.delete_requested.connect(self._delete)
            self.grid.insertWidget(self.grid.count() - 1, card)
        self.grid_host.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.count_badge.setText(tn("images.count", len(items)))

    # ---------------------------------------------------------------- actions
    def _open(self, item: MediaItem) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.path))):
            self.notify.emit(tr("media.open_failed"), "error")

    def _delete(self, item: MediaItem) -> None:
        dialog = ConfirmDialog(
            self.window(),
            tr("media.delete_title"),
            tr("media.delete_body", name=item.name),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.delete(item.path)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("media.deleted", name=item.name), "info")

    # -------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.status_badge.setText(tr("images.unavailable"))
        self.provider_badge.setText(tr("images.no_provider"))
        self.generate_button.setText(tr("images.generate"))
        self.generate_button.setToolTip(tr("images.generate_disabled", note=self.PROVIDER_NOTE))
        self.library_title.setText(tr(self.SECTION_KEY))
        self.refresh_button.setAccessibleName(tr("performance.refresh"))
        self.refresh_button.setToolTip(tr("performance.refresh"))
        self.empty.setText(tr(self.EMPTY_KEY))
        self.count_badge.setText(tr("images.count", count=len(self.items())))
        self.refresh()


class ImagesPage(MediaPage):
    KIND = "images"
    ICON = "image"
    TITLE_KEY = "images.title"
    SUBTITLE_KEY = "images.subtitle"
    SECTION_KEY = "images.library_title"
    EMPTY_KEY = "images.empty"


class VideoPage(MediaPage):
    KIND = "videos"
    ICON = "video"
    TITLE_KEY = "video.title"
    SUBTITLE_KEY = "video.subtitle"
    SECTION_KEY = "video.library_title"
    EMPTY_KEY = "video.empty"
    PROVIDER_NOTE = VIDEO_PROVIDER_NOTE
