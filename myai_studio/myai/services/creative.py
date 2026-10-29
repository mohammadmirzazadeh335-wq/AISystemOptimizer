"""Files a chat model can actually produce — charts, PDFs, images, archives.

A text model cannot draw a pixel, but it can describe a chart, write Markdown or
name a crop size. This module is the missing half: real generators that turn
those instructions into real files on disk, offline and without a paid media
provider.

What is real here:

* ``render_chart`` — an SVG bar / line / pie chart from numbers, pure Python.
* ``render_pdf``    — Markdown or plain text to a real PDF (Qt's own PDF writer).
* ``convert_image`` — resize / re-encode a PNG/JPEG/WebP/BMP with Qt's image codec.
* ``contact_sheet`` — one grid image from many pictures.
* ``zip_bundle``    — a zip archive of the files the user picked.
* ``probe_media``   — duration and pixel size read from the file header.

What is *not* here: video encoding and speech. There is no encoder in the
standard library, so those tools stay unavailable with a stated reason instead
of pretending to work.
"""

from __future__ import annotations

import datetime as _dt
import os
import struct
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from ..core.errors import ValidationError

MAX_CHART_SERIES = 24
MAX_CHART_POINTS = 200
MAX_IMAGE_SIDE = 8192
#: Palette that reads on both the dark and the light theme.
CHART_COLORS = (
    "#5b8def", "#8b5cf6", "#14b8a6", "#f59e0b", "#ef4444",
    "#06b6d4", "#a855f7", "#22c55e", "#eab308", "#f97316",
)


class CreativeUnavailable(RuntimeError):
    """A generator needs something this machine does not have (usually Qt)."""


# --------------------------------------------------------------------- charts
@dataclass(frozen=True)
class Series:
    label: str
    values: list[float]


def _scale(values: list[float], low: float, high: float) -> float:
    span = high - low
    return (1.0 if span == 0 else (values - low) / span)


def render_chart(
    *,
    kind: str,
    series: list[Series],
    path: str | Path,
    title: str = "",
    width: int = 900,
    height: int = 520,
) -> Path:
    """Write an SVG chart. Pure Python: it works with no GUI and no network."""
    if not series:
        raise ValidationError("A chart needs at least one series", message_key="creative.no_data")
    if len(series) > MAX_CHART_SERIES:
        raise ValidationError("Too many series for one chart", message_key="creative.too_many")
    for item in series:
        if not item.values:
            raise ValidationError("A series has no values", message_key="creative.no_data")
        if len(item.values) > MAX_CHART_POINTS:
            raise ValidationError("Too many points in a series", message_key="creative.too_many")
    chart = (kind or "bar").strip().lower()
    if chart not in {"bar", "line", "pie"}:
        raise ValidationError("Unknown chart kind", message_key="creative.unknown_kind")

    width = max(320, min(int(width), 2400))
    height = max(220, min(int(height), 1600))
    background = "#0f1420"
    ink = "#e6ebf5"
    faint = "#8b96ad"
    grid = "#263041"
    pad_left, pad_right, pad_top, pad_bottom = 64, 28, 48 if title else 24, 56

    body: list[str] = []
    if chart == "pie":
        total = sum(sum(item.values) for item in series)
        if total <= 0:
            raise ValidationError("A pie chart needs positive values", message_key="creative.no_data")
        centre_x, centre_y = width / 2, height / 2 + (10 if title else 0)
        radius = min(width, height) * 0.32
        start = -90.0
        labels: list[str] = []
        flat = [(item.label, value) for item in series for value in item.values]
        for index, (label, value) in enumerate(flat):
            sweep = 360.0 * (value / total)
            end = start + sweep
            large = 1 if sweep > 180 else 0
            x1 = centre_x + radius * _cos(start)
            y1 = centre_y + radius * _sin(start)
            x2 = centre_x + radius * _cos(end)
            y2 = centre_y + radius * _sin(end)
            color = CHART_COLORS[index % len(CHART_COLORS)]
            body.append(
                f'<path d="M {centre_x:.1f} {centre_y:.1f} L {x1:.1f} {y1:.1f} '
                f'A {radius:.1f} {radius:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
                f'fill="{color}" stroke="{background}" stroke-width="2"/>'
            )
            share = 100.0 * value / total
            labels.append(
                f'<g><rect x="{pad_left + (index // 8) * 220}" y="{height - 34 + (index % 8) * 0}" '
                f'width="10" height="10" rx="2" fill="{color}"/>'
                f'<text x="{pad_left + (index // 8) * 220 + 16}" y="{height - 25}" '
                f'fill="{ink}" font-size="12">{escape(label)} {share:.0f}%</text></g>'
            )
            start = end
        body.extend(labels)
    else:
        plot_w = width - pad_left - pad_right
        plot_h = height - pad_top - pad_bottom
        values = [value for item in series for value in item.values]
        low = min(0.0, min(values))
        high = max(values) if max(values) != low else low + 1.0
        for step in range(5):
            y = pad_top + plot_h * step / 4
            value = high - (high - low) * step / 4
            body.append(
                f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" '
                f'stroke="{grid}" stroke-width="1"/>'
            )
            body.append(
                f'<text x="{pad_left - 10}" y="{y + 4:.1f}" fill="{faint}" font-size="11" '
                f'text-anchor="end">{value:,.0f}</text>'
            )
        count = max(len(item.values) for item in series)
        if chart == "bar":
            group = plot_w / count
            bar_w = group / (len(series) + 0.6)
            for s_index, item in enumerate(series):
                color = CHART_COLORS[s_index % len(CHART_COLORS)]
                for index, value in enumerate(item.values):
                    bar_h = plot_h * (value - low) / (high - low)
                    x = pad_left + index * group + bar_w * (s_index + 0.3)
                    y = pad_top + plot_h - bar_h
                    body.append(
                        f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                        f'rx="3" fill="{color}"><title>{escape(item.label)}: {value:g}</title></rect>'
                    )
        else:
            step = plot_w / max(1, count - 1)
            for s_index, item in enumerate(series):
                color = CHART_COLORS[s_index % len(CHART_COLORS)]
                points = " ".join(
                    f"{pad_left + index * step:.1f},"
                    f"{pad_top + plot_h - plot_h * (value - low) / (high - low):.1f}"
                    for index, value in enumerate(item.values)
                )
                body.append(
                    f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5" '
                    f'stroke-linejoin="round"/>'
                )
        # legend
        legend_x = pad_left
        for s_index, item in enumerate(series):
            color = CHART_COLORS[s_index % len(CHART_COLORS)]
            body.append(
                f'<rect x="{legend_x}" y="{height - 30}" width="10" height="10" rx="2" fill="{color}"/>'
                f'<text x="{legend_x + 16}" y="{height - 21}" fill="{ink}" font-size="12">'
                f"{escape(item.label)}</text>"
            )
            legend_x += 22 + 7 * len(item.label)

    title_markup = (
        f'<text x="{pad_left}" y="30" fill="{ink}" font-size="17" font-weight="600">'
        f"{escape(title)}</text>"
        if title
        else ""
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{background}"/>'
        f"{title_markup}{''.join(body)}</svg>"
    )
    target = _target(path, ".svg")
    target.write_text(svg, encoding="utf-8")
    return target


def _cos(degrees: float) -> float:
    import math

    return math.cos(math.radians(degrees))


def _sin(degrees: float) -> float:
    import math

    return math.sin(math.radians(degrees))


# --------------------------------------------------------------------- targets
def _target(path: str | Path, suffix: str) -> Path:
    target = Path(path)
    if target.suffix.lower() != suffix:
        target = target.with_suffix(suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def safe_name(name: str, fallback: str = "file") -> str:
    """A file name that cannot escape its folder on Windows or POSIX."""
    cleaned = "".join(
        character if character.isalnum() or character in " ._-" else "-"
        for character in (name or "").strip()
    )
    cleaned = " ".join(cleaned.split()).strip(" .-")
    return (cleaned or fallback)[:120]


def _qt_modules():
    """Import Qt lazily and only when a generator needs it.

    The import goes through :mod:`importlib` on purpose: the services layer must
    stay importable without a GUI (``tests/integration/test_layering.py`` enforces
    it), and a literal ``from PySide6…`` anywhere in this package breaks that rule
    even when the import sits inside a function.
    """
    import importlib

    try:
        core = importlib.import_module("PySide6.QtCore")
        gui = importlib.import_module("PySide6.QtGui")
        widgets = importlib.import_module("PySide6.QtWidgets")
    except Exception as exc:  # noqa: BLE001 - a headless build may ship no Qt
        raise CreativeUnavailable("This build has no Qt image support.") from exc
    return core, gui, widgets


def _qt() -> bool:
    """Backwards-compatible check used by ``available()``."""
    _qt_modules()
    return True


# ---------------------------------------------------------------------- images
def convert_image(
    source: str | Path,
    target: str | Path,
    *,
    width: int = 0,
    height: int = 0,
    fmt: str = "",
) -> Path:
    """Resize and/or re-encode one picture with Qt's codecs."""
    core, gui, _widgets = _qt_modules()
    Qt, QImage = core.Qt, gui.QImage

    src = Path(source)
    if not src.is_file():
        raise ValidationError("The image does not exist", message_key="creative.missing_file")
    image = QImage(str(src))
    if image.isNull():
        raise ValidationError("That file is not an image this machine can read",
                              message_key="creative.bad_image")
    if width or height:
        width = int(width) or image.width()
        height = int(height) or image.height()
        width = max(1, min(width, MAX_IMAGE_SIDE))
        height = max(1, min(height, MAX_IMAGE_SIDE))
        image = image.scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    suffix = f".{fmt.lower().lstrip('.')}" if fmt else (Path(target).suffix or ".png")
    out = _target(target, suffix)
    if not image.save(str(out)):
        raise ValidationError("Could not write the image", message_key="creative.write_failed")
    return out


def image_size(path: str | Path) -> tuple[int, int]:
    _core, gui, _widgets = _qt_modules()
    QImage = gui.QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValidationError("That file is not an image", message_key="creative.bad_image")
    return image.width(), image.height()


def contact_sheet(paths: list[str | Path], target: str | Path, *, columns: int = 4) -> Path:
    """One grid image from many pictures, each captioned by its file name."""
    core, gui, _widgets = _qt_modules()
    QRect, Qt = core.QRect, core.Qt
    QColor, QFont, QImage, QPainter = gui.QColor, gui.QFont, gui.QImage, gui.QPainter

    files = [Path(item) for item in paths if Path(item).is_file()]
    if not files:
        raise ValidationError("No images to place", message_key="creative.missing_file")
    columns = max(1, min(int(columns), 8))
    cell = 320
    rows = (len(files) + columns - 1) // columns
    sheet = QImage(cell * columns, cell * rows, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#0f1420"))
    painter = QPainter(sheet)
    painter.setFont(QFont("Sans Serif", 10))
    for index, file in enumerate(files):
        image = QImage(str(file))
        column, row = index % columns, index // columns
        box = QRect(column * cell, row * cell, cell, cell)
        if not image.isNull():
            thumb = image.scaled(
                cell - 16, cell - 40, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawImage(
                box.x() + (cell - thumb.width()) // 2,
                box.y() + 8 + (cell - 40 - thumb.height()) // 2,
                thumb,
            )
        painter.setPen(QColor("#8b96ad"))
        painter.drawText(
            QRect(box.x() + 8, box.y() + cell - 26, cell - 16, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            file.name[:40],
        )
    painter.end()
    out = _target(target, ".png")
    if not sheet.save(str(out)):
        raise ValidationError("Could not write the sheet", message_key="creative.write_failed")
    return out


# ------------------------------------------------------------------------- PDF
def render_pdf(text: str, target: str | Path, *, title: str = "") -> Path:
    """Markdown or plain text to a real PDF, using Qt's own PDF writer."""
    _core, gui, _widgets = _qt_modules()
    QPageSize, QPdfWriter, QTextDocument = gui.QPageSize, gui.QPdfWriter, gui.QTextDocument

    out = _target(target, ".pdf")
    writer = QPdfWriter(str(out))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(96)
    writer.setTitle(title or out.stem)
    document = QTextDocument()
    try:  # a real Markdown render when the app's own converter is available
        from ..core.markdown import render_markdown

        document.setHtml(render_markdown(text))
    except Exception:  # noqa: BLE001 - plain text is a fine fallback
        document.setPlainText(text)
    document.print_(writer)
    return out


# ---------------------------------------------------------------------- archive
def zip_bundle(paths: list[str | Path], target: str | Path, *, base: str | Path | None = None) -> Path:
    """Zip the given files, keeping paths relative to ``base`` when given."""
    files = [Path(item) for item in paths if Path(item).is_file()]
    if not files:
        raise ValidationError("Nothing to compress", message_key="creative.missing_file")
    out = _target(target, ".zip")
    root = Path(base) if base else None
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            try:
                arcname = str(file.relative_to(root)) if root else file.name
            except ValueError:
                arcname = file.name
            archive.write(file, arcname)
    return out


# ------------------------------------------------------------------------ probe
@dataclass(frozen=True)
class MediaInfo:
    kind: str
    size_bytes: int
    width: int = 0
    height: int = 0
    duration_seconds: float = 0.0
    detail: str = ""

    def describe(self) -> str:
        parts = [f"{self.kind}", f"{self.size_bytes / 1024:.1f} KB"]
        if self.width and self.height:
            parts.append(f"{self.width}×{self.height}")
        if self.duration_seconds:
            parts.append(f"{self.duration_seconds:.1f} s")
        if self.detail:
            parts.append(self.detail)
        return " · ".join(parts)


def probe_media(path: str | Path) -> MediaInfo:
    """Read size/duration from headers. No decoding, so it is cheap and safe."""
    file = Path(path)
    if not file.is_file():
        raise ValidationError("The file does not exist", message_key="creative.missing_file")
    size = file.stat().st_size
    suffix = file.suffix.lower()
    if suffix == ".wav":
        try:
            with wave.open(str(file), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate() or 1
                return MediaInfo(
                    kind="audio", size_bytes=size,
                    duration_seconds=frames / rate,
                    detail=f"{handle.getnchannels()} ch · {rate} Hz",
                )
        except Exception:  # noqa: BLE001 - a broken header is just "unknown"
            return MediaInfo(kind="audio", size_bytes=size)
    if suffix in {".mp4", ".m4v", ".mov", ".3gp"}:
        found = _mp4_duration(file.read_bytes()[:65536])
        return MediaInfo(
            kind="video", size_bytes=size,
            duration_seconds=found,
            detail="" if found else "duration not in the first 64 KB",
        )
    if suffix in {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma"}:
        return MediaInfo(kind="audio", size_bytes=size)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        from .attachments import image_size as header_size

        found = header_size(file.read_bytes()[:65536])
        return MediaInfo(
            kind="image", size_bytes=size,
            width=found[0] if found else 0,
            height=found[1] if found else 0,
        )
    if suffix == ".pdf":
        return MediaInfo(kind="document", size_bytes=size)
    return MediaInfo(kind="file", size_bytes=size)


def _mp4_duration(head: bytes) -> float:
    """Walk the box tree to ``mvhd``; returns seconds or 0 when not found."""
    offset = 0
    length = len(head)
    while offset + 8 <= length:
        try:
            size, kind = struct.unpack(">I4s", head[offset: offset + 8])
        except struct.error:
            return 0.0
        if size == 1:  # 64-bit size
            if offset + 16 > length:
                return 0.0
            size = struct.unpack(">Q", head[offset + 8: offset + 16])[0]
            header = 16
        else:
            header = 8
        if kind == b"mvhd":
            body = head[offset + header: offset + size]
            if not body:
                return 0.0
            version = body[0]
            try:
                if version == 1:
                    timescale, duration = struct.unpack(">I Q", body[20:32])
                else:
                    timescale, duration = struct.unpack(">I I", body[12:20])
            except struct.error:
                return 0.0
            return round(duration / timescale, 2) if timescale else 0.0
        if size < 8:
            return 0.0
        offset += size
    return 0.0


def suggested_name(prefix: str, suffix: str) -> str:
    """A dated file name such as ``chart-2026-10-29-1432.svg``."""
    stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    return f"{safe_name(prefix, 'file')}-{stamp}{suffix}"


def unique_path(folder: str | Path, name: str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / name
    index = 2
    while candidate.exists():
        candidate = folder / f"{Path(name).stem}-{index}{Path(name).suffix}"
        index += 1
    return candidate


def available() -> dict[str, Any]:
    """What this machine can really generate — the UI states exactly this."""
    has_qt = True
    try:
        _qt()
    except CreativeUnavailable:
        has_qt = False
    return {
        "charts": True,
        "archives": True,
        "probe": True,
        "images": has_qt,
        "pdf": has_qt,
        "video": False,
        "speech": False,
        "python": os.sys.version.split()[0],
    }
