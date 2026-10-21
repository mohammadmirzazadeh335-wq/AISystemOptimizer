"""Vector icon system.

Icons are described once as SVG strokes and recoloured per theme at render
time.  This keeps the icon set visually consistent and avoids emoji or bitmap
assets.  Rendering is cached by (name, colour, size, stroke).
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)

# Inner geometry for every icon (24x24 grid, stroked).
ICONS: dict[str, str] = {
    "chat": '<path d="M20.5 11.3a8.3 8.3 0 0 1-8.3 8.2H7.4L3.5 22v-7.3a8.3 8.3 0 0 1 4-7.1 8.3 8.3 0 0 1 5-1.6 8.3 8.3 0 0 1 8 5.2z"/><path d="M8.4 11h7.2M8.4 14.4h4.4"/>',
    "search": '<circle cx="11" cy="11" r="6.4"/><path d="m20 20-3.8-3.8"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3.5 7.6A2.1 2.1 0 0 1 5.6 5.5h3.2l2 2.4h7.6a2.1 2.1 0 0 1 2.1 2.1v7.4a2.1 2.1 0 0 1-2.1 2.1H5.6a2.1 2.1 0 0 1-2.1-2.1z"/>',
    "folder-plus": '<path d="M3.5 7.6A2.1 2.1 0 0 1 5.6 5.5h3.2l2 2.4h7.6a2.1 2.1 0 0 1 2.1 2.1v7.4a2.1 2.1 0 0 1-2.1 2.1H5.6a2.1 2.1 0 0 1-2.1-2.1z"/><path d="M12 11v5M9.5 13.5h5"/>',
    "pin": '<path d="M12 16.5V22"/><path d="M8.2 3.5h7.6l-1 5.2 2.7 3v1.8H6.5v-1.8l2.7-3z"/>',
    "sparkles": '<path d="M12 3.5l1.7 4.6 4.6 1.7-4.6 1.7L12 16.1l-1.7-4.6-4.6-1.7 4.6-1.7z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "code": '<path d="m8.5 8-4.5 4 4.5 4"/><path d="m15.5 8 4.5 4-4.5 4"/><path d="m13.5 5-3 14"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.6"/><circle cx="9" cy="9.5" r="1.7"/><path d="m20.5 15.5-4.8-4.4L6 19.5"/>',
    "globe": '<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2M12 3.4c2.4 2.3 3.6 5.2 3.6 8.6s-1.2 6.3-3.6 8.6c-2.4-2.3-3.6-5.2-3.6-8.6s1.2-6.3 3.6-8.6z"/>',
    "video": '<rect x="3" y="6" width="12.5" height="12" rx="2.4"/><path d="m15.5 10.5 5.5-3v9l-5.5-3z"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3"/><circle cx="15" cy="7" r="2.1"/><circle cx="9" cy="12" r="2.1"/><circle cx="15" cy="17" r="2.1"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "chevron-up": '<path d="m6 14.5 6-6 6 6"/>',
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "chevron-left": '<path d="m14.5 6-6 6 6 6"/>',
    "arrow-up": '<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>',
    "arrow-down": '<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>',
    "arrow-right": '<path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5"/>',
    "arrow-up-right": '<path d="M7 17 17 7M9 7h8v8"/>',
    "send": '<path d="M12 19V6M6.8 11 12 5.8 17.2 11"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2.6" fill="{color}" stroke="none"/>',
    "attach": '<path d="M19.5 11.6 12 19.1a5 5 0 0 1-7.1-7.1l7.8-7.8a3.4 3.4 0 0 1 4.8 4.8l-7.6 7.6a1.8 1.8 0 0 1-2.6-2.6l6.9-6.9"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "more": '<circle cx="5.5" cy="12" r="1.2" fill="{color}"/><circle cx="12" cy="12" r="1.2" fill="{color}"/><circle cx="18.5" cy="12" r="1.2" fill="{color}"/>',
    "panel-right": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.6"/><path d="M15 4.8v14.4"/>',
    "panel-left": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.6"/><path d="M9 4.8v14.4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/>',
    "moon": '<path d="M20 14.4A8.6 8.6 0 0 1 9.6 4 8.6 8.6 0 1 0 20 14.4z"/>',
    "monitor": '<rect x="3" y="4.5" width="18" height="12.5" rx="2.4"/><path d="M8 21h8M12 17.5V21"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2.4"/><path d="M15.5 8.5v-2A2 2 0 0 0 13.5 4.5h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.8h5V7M6.5 7l.9 12.2a2 2 0 0 0 2 1.8h5.2a2 2 0 0 0 2-1.8L17.5 7M10 11v6M14 11v6"/>',
    "edit": '<path d="M4 20h4.2L19 9.2a2.3 2.3 0 0 0-3.2-3.2L5 16.8z"/><path d="m14.8 7 2.2 2.2"/>',
    "download": '<path d="M12 4v10M7.5 10 12 14.5 16.5 10M4.5 19.5h15"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4.5 19.5h15"/>',
    "check": '<path d="m4.5 12.5 5 5 10-11"/>',
    "alert": '<path d="M12 3.8 21 20H3z"/><path d="M12 9.5v4.5M12 17.2v.1"/>',
    "info": '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5M12 8v.1"/>',
    "wrench": '<path d="M14.8 6.2a4.4 4.4 0 0 0-5.7 5.7L4 17v3h3l5.1-5.1a4.4 4.4 0 0 0 5.7-5.7l-2.5 2.5-2.6-.6-.6-2.6z"/>',
    "database": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/>',
    "activity": '<path d="M3.5 12h4l2.5-6.5 4 13L16.5 12h4"/>',
    "external": '<path d="M14 4.5h5.5V10M19 5l-8 8"/><path d="M18.5 14v4.5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2H10"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 6.1"/><path d="M20 4.5V11h-6.5"/>',
    "lock": '<rect x="4.5" y="10" width="15" height="10.5" rx="2.6"/><path d="M8 10V7.4a4 4 0 0 1 8 0V10M12 14v3"/>',
    "user": '<circle cx="12" cy="8.2" r="3.8"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    "play": '<path d="M7.5 4.8 19 12 7.5 19.2z"/>',
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2.6"/><path d="m7 9 3 3-3 3M12.5 15H17"/>',
    "file": '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"/><path d="M13.5 3.5V9H19"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/><path d="m3 17.5 9 5 9-5"/>',
    "zap": '<path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12z"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5.4l3.4 2"/>',
    "cpu": '<rect x="6.5" y="6.5" width="11" height="11" rx="2.2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
    "hard-drive": '<rect x="3" y="5" width="18" height="14" rx="2.6"/><path d="M3 13h18M7 16.5h.1M11 16.5h.1"/>',
    "shield": '<path d="M12 3 19.5 6v6c0 4.4-3 7.6-7.5 9-4.5-1.4-7.5-4.6-7.5-9V6z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
    "book-open": '<path d="M12 6.2C10.4 4.9 8.5 4.2 5.6 4.2H4v13.2h1.6c2.9 0 4.8.6 6.4 1.9 1.6-1.3 3.5-1.9 6.4-1.9H20V4.2h-1.6c-2.9 0-4.8.7-6.4 2z"/><path d="M12 6.2v13.1"/>',
    "braces": '<path d="M9 4.5c-2 0-3 .9-3 3v2.2c0 1.2-.6 1.8-2 2.3 1.4.5 2 1.1 2 2.3v2.2c0 2.1 1 3 3 3"/><path d="M15 4.5c2 0 3 .9 3 3v2.2c0 1.2.6 1.8 2 2.3-1.4.5-2 1.1-2 2.3v2.2c0 2.1-1 3-3 3"/>',
    "git": '<circle cx="6" cy="6" r="2.4"/><circle cx="6" cy="18" r="2.4"/><circle cx="18" cy="8" r="2.4"/><path d="M6 8.4v7.2M18 10.4c0 3.2-2.4 4.2-5.4 4.2H8.4"/>',
    "history": '<path d="M3.6 12a8.4 8.4 0 1 0 2.5-6"/><path d="M3.5 4.5V10H9"/><path d="M12 8v4.6l3.2 1.9"/>',
    "plug": '<path d="M9 3v5M15 3v5"/><path d="M6.5 8h11v3.2a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.7V21"/>',
    "book": '<path d="M4 5.2A2.2 2.2 0 0 1 6.2 3H20v15.5H6.2A2.2 2.2 0 0 0 4 20.7z"/><path d="M4 20.7V5.2M8.5 7.5h7"/>',
    "list-check": '<path d="M9.5 6.5h11M9.5 12h11M9.5 17.5h11"/><path d="m3.5 6.5 1.4 1.4 2.4-2.6M3.5 12l1.4 1.4 2.4-2.6M3.5 17.5l1.4 1.4 2.4-2.6"/>',
    "gauge": '<path d="M4.2 17.5a8.6 8.6 0 1 1 15.6 0"/><path d="m12 12.5 4-4"/><circle cx="12" cy="12.5" r="1.2"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.6 0 2.3-1 2.3-2.1 0-1.7 1-2.4 2.6-2.4h1.6a2 2 0 0 0 2-2A8.5 8.5 0 0 0 12 3.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>',
    "key": '<circle cx="8" cy="15.5" r="4.5"/><path d="m11.5 12 8-8M16 7.5l2.5 2.5M14 5l3 3"/>',
    "cloud": '<path d="M7.5 18.5a4.5 4.5 0 0 1-.6-8.9A6 6 0 0 1 18.6 10a4.2 4.2 0 0 1-.9 8.5z"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M4 4l16 16M10 6c.7-.2 1.3-.3 2-.3 6 0 9.5 6.3 9.5 6.3a17 17 0 0 1-3.2 4.1M6.3 7.8A17 17 0 0 0 2.5 12s3.5 6.5 9.5 6.5c1.4 0 2.7-.3 3.8-.9"/>',
    "maximize": '<path d="M9 4H4v5M15 4h5v5M15 20h5v-5M9 20H4v-5"/>',
    "minimize": '<path d="M5 12h14"/>',
    "enter": '<path d="M20 5v6.5a3.5 3.5 0 0 1-3.5 3.5H5"/><path d="m9 10.5-4.5 4.5L9 19.5"/>',
    "command": '<path d="M8.5 4.5a2.5 2.5 0 1 1 2.5 2.5v10a2.5 2.5 0 1 1-2.5-2.5h7a2.5 2.5 0 1 1-2.5 2.5V7a2.5 2.5 0 1 1 2.5 2.5z"/>',
    "star": '<path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1.1 5.9-5.3-2.9-5.3 2.9 1.1-5.9L3.5 9.7l5.9-.8z"/>',
    "inbox": '<path d="M3.5 12.5h5l1.5 3h4l1.5-3h5"/><path d="M5.8 4.5h12.4l2.3 8v5a2.2 2.2 0 0 1-2.2 2.2H5.7a2.2 2.2 0 0 1-2.2-2.2v-5z"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.6 1.6"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.6-1.6"/>',
    "music": '<circle cx="7" cy="17" r="3"/><circle cx="18" cy="15" r="3"/><path d="M10 17V5.5l8-2V15"/>',
    "type": '<path d="M5 6V4.5h14V6M12 4.5V19.5M9 19.5h6"/>',
    "sliders": '<path d="M4 7h6M14 7h6M4 17h10M18 17h2"/><circle cx="12" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>',
    "smile": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 14s1.3 2 3.5 2 3.5-2 3.5-2M9 9.5h.1M15 9.5h.1"/>',
    "server": '<rect x="3.5" y="4" width="17" height="7" rx="2"/><rect x="3.5" y="13" width="17" height="7" rx="2"/><path d="M7 7.5h.1M7 16.5h.1"/>',
    "route": '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
    "wand": '<path d="M15 4V2.5M15 11.5V10M11.5 7H10M20 7h-1.5M18.5 3.5 19.5 4.5M18.3 10 19.3 11M11.7 3.6 12.7 4.6"/><path d="M3 21 15.5 8.5l2 2L5 23z" transform="translate(0 -2)"/>',
}


@lru_cache(maxsize=512)
def _renderer(svg: str) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(svg.encode("utf-8")))


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str, size: int = 20, stroke: float = 1.7, dpr: float = 2.0) -> QPixmap:
    body = ICONS.get(name)
    if body is None:
        body = ICONS["info"]
    body = body.replace("{color}", color)
    svg = _SVG_HEAD.format(color=color, stroke=stroke, body=body)
    renderer = _renderer(svg)
    px = max(1, int(round(size * dpr)))
    image = QPixmap(px, px)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def icon(name: str, color: str, size: int = 20, stroke: float = 1.7, dpr: float = 2.0) -> QIcon:
    return QIcon(pixmap(name, color, size, stroke, dpr))


def draw(painter: QPainter, name: str, rect, color: str, stroke: float = 1.7) -> None:
    body = ICONS.get(name, ICONS["info"]).replace("{color}", color)
    svg = _SVG_HEAD.format(color=color, stroke=stroke, body=body)
    renderer = _renderer(svg)
    renderer.render(painter, QRectF(rect))


class IconCache:
    """Theme-aware icon cache handed to widgets."""

    def __init__(self) -> None:
        self._color = "#FFFFFF"
        self._muted = "#999999"
        self._accent = "#4C8DFF"

    def update(self, color: str, muted: str, accent: str) -> None:
        self._color = color
        self._muted = muted
        self._accent = accent

    def get(self, name: str, size: int = 20, tone: str = "normal", stroke: float = 1.7) -> QIcon:
        color = {"normal": self._color, "muted": self._muted, "accent": self._accent}.get(tone, self._color)
        return icon(name, color, size, stroke)

    def px(self, name: str, size: int = 20, tone: str = "normal", stroke: float = 1.7) -> QPixmap:
        color = {"normal": self._color, "muted": self._muted, "accent": self._accent}.get(tone, self._color)
        return pixmap(name, color, size, stroke)

    @property
    def color(self) -> str:
        return self._color

    @property
    def muted(self) -> str:
        return self._muted

    @property
    def accent(self) -> str:
        return self._accent
