"""Code Studio: a real project tree, a real editor and real execution.

The page never pretends. A file is read from disk, typed changes are written back
to that same file, and ``Run`` executes it with the toolchain that was actually
detected on this machine. When a toolchain is missing the page names the missing
executable instead of showing a dead button without a reason.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...services.projects import Project, ProjectService
from ...services.runner import Runner, RunResult
from ...services.toolchains import ToolchainRegistry, ToolchainUnavailable, registry
from ..theme import runtime
from ..widgets.fields import FlowLayout, SelectField
from ..widgets.foundation import Badge
from .page_base import PageShell, ghost_button, primary_button, secondary_button

# --------------------------------------------------------------------- syntax
KEYWORDS = {
    "python": (
        "def class return if elif else for while import from as pass break continue "
        "try except finally with lambda yield global nonlocal raise assert del in is "
        "not and or None True False async await"
    ),
    "javascript": (
        "function const let var return if else for while class new try catch finally "
        "throw import export from default async await true false null undefined this"
    ),
    "typescript": (
        "function const let var return if else for while class new try catch finally "
        "throw import export from default async await true false null undefined this "
        "interface type extends implements public private readonly"
    ),
    "c": (
        "int char float double void long short unsigned signed const static struct "
        "union enum typedef if else for while do return break continue switch case "
        "default sizeof include"
    ),
    "cpp": (
        "int char float double void long short unsigned signed const static struct "
        "class public private protected virtual override template typename namespace "
        "using new delete return if else for while do switch case default auto"
    ),
    "json": "true false null",
    "bash": "if then else fi for while do done case esac function export local echo cd",
    "sql": "select from where insert into values update delete create table drop alter",
}

COMMENT_RULES = {
    "python": [("#", "")],
    "javascript": [("//", "")],
    "typescript": [("//", "")],
    "c": [("//", ""), ("/*", "*/")],
    "cpp": [("//", ""), ("/*", "*/")],
    "bash": [("#", "")],
    "sql": [("--", "")],
}
STRING_RULES = {
    "python": [('"""', '"""'), ("'''", "'''"), ('"', '"'), ("'", "'")],
    "javascript": [("`", "`"), ('"', '"'), ("'", "'")],
    "typescript": [("`", "`"), ('"', '"'), ("'", "'")],
    "c": [('"', '"')],
    "cpp": [('"', '"')],
    "json": [('"', '"')],
    "bash": [('"', '"'), ("'", "'")],
    "sql": [("'", "'")],
}


def _alpha(token: str, alpha: float) -> QColor:
    color = QColor(runtime.theme().color(token))
    color.setAlphaF(alpha)
    return color


class CodeHighlighter(QSyntaxHighlighter):
    """Small, dependency-free highlighter for the languages the editor opens."""

    def __init__(self, document: QTextDocument, language: str = "text") -> None:
        super().__init__(document)
        self._language = language
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        self._language = language
        self._build_rules()
        self.rehighlight()

    def refresh(self) -> None:
        self._build_rules()
        self.rehighlight()

    def _build_rules(self) -> None:
        theme = runtime.theme()
        rules: list[tuple[re.Pattern, QTextCharFormat]] = []

        words = KEYWORDS.get(self._language, "").split()
        if words:
            keyword = QTextCharFormat()
            keyword.setForeground(QColor(theme.color("accent")))
            keyword.setFontWeight(QFont.Weight.DemiBold)
            pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in words) + r")\b")
            rules.append((pattern, keyword))

        string = QTextCharFormat()
        string.setForeground(QColor(theme.color("success")))
        for opening, closing in STRING_RULES.get(self._language, []):
            rules.append(
                (re.compile(re.escape(opening) + r".*?" + re.escape(closing)), string)
            )

        number = QTextCharFormat()
        number.setForeground(QColor(theme.color("warning")))
        rules.append((re.compile(r"\b\d+(?:\.\d+)?\b"), number))

        comment = QTextCharFormat()
        comment.setForeground(QColor(theme.color("text_faint")))
        comment.setFontItalic(True)
        for opening, closing in COMMENT_RULES.get(self._language, []):
            if closing:
                rules.append(
                    (re.compile(re.escape(opening) + r".*?" + re.escape(closing)), comment)
                )
            else:
                rules.append((re.compile(re.escape(opening) + r"[^\n]*"), comment))

        if self._language == "markdown":
            heading = QTextCharFormat()
            heading.setForeground(QColor(theme.color("accent")))
            heading.setFontWeight(QFont.Weight.DemiBold)
            rules.append((re.compile(r"^#{1,6} .*$"), heading))
            inline = QTextCharFormat()
            inline.setForeground(QColor(theme.color("success")))
            rules.append((re.compile(r"`[^`\n]+`"), inline))
        self._rules = rules

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class ElidedLabel(QLabel):
    """A label that shortens itself instead of painting under its neighbour."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._full_text = text
        super().setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text
        self._apply()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        available = max(0, self.width() - runtime.px(2))
        if available <= 0:
            # Not laid out yet: keep the real name; the next resize elides it.
            if super().text() != self._full_text:
                QLabel.setText(self, self._full_text)
            return
        elided = self.fontMetrics().elidedText(self._full_text, self._mode, available)
        if elided != super().text():
            QLabel.setText(self, elided)


class _LineNumbers(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self._editor.line_number_width(), self._editor.height())

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """Plain text editor with line numbers, current-line highlight and hard tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(runtime.mono_font(12))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(runtime.mono_font(12)).horizontalAdvance(" ") * 4)
        self._numbers = _LineNumbers(self)
        self._highlighter = CodeHighlighter(self.document(), "text")
        self.blockCountChanged.connect(self._sync_margin)
        self.updateRequest.connect(self._scroll_numbers)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._sync_margin()

    # ------------------------------------------------------------------ public
    def set_language(self, language: str) -> None:
        self._highlighter.set_language(language)

    def refresh_theme(self) -> None:
        self._highlighter.refresh()
        self._highlight_current_line()
        self._numbers.update()

    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return runtime.px(12) + digits * QFontMetrics(self.font()).horizontalAdvance("9")

    # ---------------------------------------------------------------- internals
    def _sync_margin(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)
        self._numbers.resize(self.line_number_width(), self.viewport().height() + runtime.px(4))
        self._numbers.move(0, 0)

    def _scroll_numbers(self, rect: QRect, dy: int) -> None:  # noqa: N802 - Qt API
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(0, rect.y(), self._numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._sync_margin()

    def paint_line_numbers(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self._numbers)
        painter.fillRect(event.rect(), QColor(runtime.theme().color("surface")))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        line_height = QFontMetrics(self.font()).height()
        current = self.textCursor().blockNumber()
        painter.setFont(self.font())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(
                    QColor(runtime.theme().color("text_muted" if number == current else "text_faint"))
                )
                painter.drawText(
                    0,
                    int(top),
                    self._numbers.width() - runtime.px(6),
                    line_height,
                    Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(_alpha("accent", 0.08))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        cursor = self.textCursor()
        cursor.clearSelection()
        selection.cursor = cursor
        self.setExtraSelections([selection])

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            line = self.textCursor().block().text()
            extra = 0
            if line.rstrip().endswith(":"):
                extra = 4
            indent = len(line) - len(line.lstrip(" ")) + extra
            super().keyPressEvent(event)
            if indent:
                self.insertPlainText(" " * indent)
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._numbers.resize(self.line_number_width(), self.viewport().height() + runtime.px(4))


# --------------------------------------------------------------------- bridge
class _RunBridge(QObject):
    """Queued-signal bridge so the worker thread never touches a widget."""

    output = Signal(str, str)
    finished = Signal(object)


class CodePage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__(
            "code.title",
            "code.subtitle",
            icon_name="code",
            scroll=False,
            stretch=False,
            actions_below=True,
        )
        self.context = context
        self.projects = ProjectService(context.paths, context.settings)
        self.runner = Runner()
        self.toolchains: ToolchainRegistry = registry()
        self.project: Project | None = None
        self.current_file: str | None = None
        self._dirty = False
        self._clean_text = ""
        self._run_thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._quiet_save = False
        self._user_split = False
        self._bridge = _RunBridge(self)
        self._bridge.output.connect(self._on_output)
        self._bridge.finished.connect(self._on_run_finished)
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(2500)
        self._autosave.timeout.connect(self._autosave_tick)
        self._build()
        self._restore_project()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        self.actions_flow = FlowLayout(spacing=runtime.px(7))
        host = QWidget()
        host.setLayout(self.actions_flow)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.actions_row.addWidget(host, 1)

        self.open_button = primary_button(tr("code.open_folder"), "folder")
        self.open_button.clicked.connect(self.choose_folder)
        self.actions_flow.addWidget(self.open_button)
        self.new_project_button = secondary_button(tr("code.new_project"), "plus")
        self.new_project_button.clicked.connect(self.new_project)
        self.actions_flow.addWidget(self.new_project_button)
        self.save_button = secondary_button(tr("code.save"), "check")
        self.save_button.setShortcut("Ctrl+S")
        self.save_button.clicked.connect(self.save_file)
        self.actions_flow.addWidget(self.save_button)
        self.run_button = primary_button(tr("code.run"), "play")
        self.run_button.setShortcut("Ctrl+R")
        self.run_button.clicked.connect(self.run_current)
        self.actions_flow.addWidget(self.run_button)
        self.stop_button = secondary_button(tr("code.stop"), "stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_run)
        self.actions_flow.addWidget(self.stop_button)

        # File actions live beside the project actions: inside a 208 px tree
        # header they left the folder name with a two-letter stub.
        self.new_file_button = ghost_button("", "plus")
        self.new_file_button.setAccessibleName(tr("code.new_file"))
        self.new_file_button.setToolTip(tr("code.new_file"))
        self.new_file_button.clicked.connect(self.new_file)
        self.actions_flow.addWidget(self.new_file_button)
        self.rename_button = ghost_button("", "edit")
        self.rename_button.setAccessibleName(tr("code.rename"))
        self.rename_button.setToolTip(tr("code.rename"))
        self.rename_button.clicked.connect(self.rename_selected)
        self.actions_flow.addWidget(self.rename_button)
        self.delete_button = ghost_button("", "trash")
        self.delete_button.setAccessibleName(tr("code.delete_file"))
        self.delete_button.setToolTip(tr("code.delete_file"))
        self.delete_button.clicked.connect(self.delete_selected)
        self.actions_flow.addWidget(self.delete_button)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(runtime.px(9))
        top = QSplitter(Qt.Orientation.Horizontal)
        top.setChildrenCollapsible(False)
        top.setHandleWidth(runtime.px(9))
        top.addWidget(self._build_tree_card())
        top.addWidget(self._build_editor_card())
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        top.setSizes([runtime.px(258), runtime.px(760)])
        top.setStretchFactor(0, 0)
        splitter.addWidget(top)
        splitter.addWidget(self._build_output_card())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([runtime.px(430), runtime.px(230)])
        top.splitterMoved.connect(self._on_splitter_moved)
        self._user_split = False
        self.top_splitter = top
        self.splitter = splitter
        self.add_widget(splitter)
        self.body.setStretchFactor(splitter, 1)

    def _build_tree_card(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(12), runtime.px(11), runtime.px(12), runtime.px(10))
        layout.setSpacing(runtime.px(7))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(4))
        self.project_label = ElidedLabel(tr("code.no_project"), mode=Qt.TextElideMode.ElideRight)
        self.project_label.setProperty("role", "section")
        head.addWidget(self.project_label, 1)
        layout.addLayout(head)

        self.project_select = SelectField([], placeholder=tr("code.recent_projects"))
        self.project_select.value_changed.connect(self._on_recent_selected)
        layout.addWidget(self.project_select)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setIndentation(runtime.px(14))
        self.tree.setMinimumHeight(runtime.px(140))
        self.tree.setAnimated(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.itemActivated.connect(self._on_tree_activated)
        theme = runtime.theme()
        self.tree.setStyleSheet(
            "QTreeWidget { background: transparent; border: none; }"
            f" QTreeWidget::item {{ padding: {runtime.px(3)}px 4px;"
            f" border-radius: {runtime.px(6)}px; }}"
            f" QTreeWidget::item:selected {{ background: {theme.alpha('accent', 0.16)};"
            f" color: {theme.color('text')}; }}"
        )
        layout.addWidget(self.tree, 1)
        self.tree_empty = QLabel(tr("code.no_project_hint"))
        self.tree_empty.setProperty("role", "faint")
        self.tree_empty.setWordWrap(True)
        layout.addWidget(self.tree_empty)
        self.toolchain_label = QLabel("")
        self.toolchain_label.setProperty("role", "faint")
        self.toolchain_label.setWordWrap(True)
        layout.addWidget(self.toolchain_label)
        self.toolchain_detail = QLabel("")
        self.toolchain_detail.setProperty("role", "warning")
        self.toolchain_detail.setWordWrap(True)
        self.toolchain_detail.setVisible(False)
        layout.addWidget(self.toolchain_detail)
        self.toolchain_toggle = ghost_button(tr("code.toolchain_details"), "info")
        self.toolchain_toggle.clicked.connect(self._toggle_toolchain_details)
        layout.addWidget(self.toolchain_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.stats_label = QLabel("")
        self.stats_label.setProperty("role", "faint")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        return frame

    def _build_editor_card(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(13), runtime.px(11), runtime.px(13), runtime.px(12))
        layout.setSpacing(runtime.px(7))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(8))
        # The badges next to it must keep their size at 1.5x; the path may yield.
        self.file_label = ElidedLabel(tr("code.no_file"))
        self.file_label.setProperty("role", "section")
        head.addWidget(self.file_label, 1)
        self.dirty_label = QLabel("")
        self.dirty_label.setProperty("role", "faint")
        head.addWidget(self.dirty_label)
        self.language_badge = Badge("—", "accent")
        head.addWidget(self.language_badge)
        self.toolchain_badge = Badge(tr("code.no_toolchain"), "violet")
        head.addWidget(self.toolchain_badge)
        layout.addLayout(head)

        self.editor = CodeEditor()
        self.editor.setAccessibleName(tr("code.editor_hint"))
        self.editor.setPlaceholderText(tr("code.editor_hint"))
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._update_cursor_label)
        layout.addWidget(self.editor, 1)

        status = QHBoxLayout()
        status.setSpacing(runtime.px(8))
        self.cursor_label = QLabel("")
        self.cursor_label.setProperty("role", "faint")
        status.addWidget(self.cursor_label, 1)
        self.binary_label = QLabel("")
        self.binary_label.setProperty("role", "warning")
        self.binary_label.setWordWrap(True)
        status.addWidget(self.binary_label, 1)
        layout.addLayout(status)
        return frame

    def _build_output_card(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(13), runtime.px(10), runtime.px(13), runtime.px(11))
        layout.setSpacing(runtime.px(7))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(8))
        title = QLabel(tr("code.output"))
        title.setProperty("role", "section")
        head.addWidget(title)
        self.status_badge = Badge(tr("code.not_run"), "muted")
        head.addWidget(self.status_badge)
        self.command_label = ElidedLabel("", mode=Qt.TextElideMode.ElideRight)
        self.command_label.setProperty("role", "mono")
        self.command_label.setWordWrap(False)
        self.command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.command_label, 1)
        self.clear_button = ghost_button(tr("code.clear"), "trash")
        self.clear_button.clicked.connect(self.clear_output)
        head.addWidget(self.clear_button)
        layout.addLayout(head)

        self.output_view = QTextEdit()
        self.output_view.setAccessibleName(tr("code.output"))
        self.output_view.setReadOnly(True)
        self.output_view.setFont(runtime.mono_font(11))
        self.output_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.output_view.setFrameShape(QFrame.Shape.NoFrame)
        self.output_view.setMinimumHeight(runtime.px(130))
        layout.addWidget(self.output_view, 1)
        return frame

    # ----------------------------------------------------------------- project
    def _restore_project(self) -> None:
        self._refresh_recent()
        last = self.projects.last_project()
        if last is not None:
            try:
                self.set_project(last, announce=False)
                return
            except Exception:  # noqa: BLE001 - a stale pointer must not break the page
                self.project = None
        self._update_project_ui()
        self._update_toolchain_summary()

    def _refresh_recent(self) -> None:
        recent = self.projects.recent()
        self.project_select.set_items([(item.path, item.name) for item in recent])
        if self.project is not None and any(item.path == self.project.path for item in recent):
            self.project_select.set_value(self.project.path)
        self.project_select.setEnabled(len(recent) > 1)
        # With a single project the field only repeated the name above it.
        self.project_select.setVisible(len(recent) > 1)

    def _on_recent_selected(self, path: str) -> None:
        if not path or (self.project is not None and path == self.project.path):
            return
        try:
            project = self.projects.open_folder(path)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.set_project(project)

    def choose_folder(self) -> None:
        start = str(self.project.root) if self.project else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, tr("code.choose_folder"), start)
        if not path:
            return
        try:
            project = self.projects.open_folder(path)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.set_project(project)
        self.notify.emit(tr("code.project_opened", name=project.name), "success")

    def new_project(self) -> None:
        name, ok = QInputDialog.getText(self, tr("code.new_project_title"), tr("code.project_name"))
        if not ok or not name.strip():
            return
        try:
            project = self.projects.create_project(name)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.set_project(project)
        self.notify.emit(tr("code.project_created", name=project.name), "success")

    def set_project(self, project: Project, announce: bool = True) -> None:  # noqa: ARG002
        self.project = project
        self.current_file = None
        self._dirty = False
        self._clean_text = ""
        self.editor.blockSignals(True)
        self.editor.clear()
        self.editor.blockSignals(False)
        self.editor.setReadOnly(False)
        self.file_label.setText(tr("code.no_file"))
        self.language_badge.setText("—")
        self.toolchain_badge.setText(tr("code.no_toolchain"))
        self.binary_label.setText("")
        self.dirty_label.setText("")
        self._populate_tree()
        self._update_project_ui()
        self._refresh_recent()
        self._update_toolchain_summary()

    def _populate_tree(self) -> None:
        self.tree.clear()
        if self.project is None:
            return
        entries = self.projects.tree(self.project)
        folders: dict[str, QTreeWidgetItem] = {"": self.tree.invisibleRootItem()}
        for entry in entries:
            parent_path = entry.relative.rsplit("/", 1)[0] if "/" in entry.relative else ""
            parent = folders.get(parent_path, self.tree.invisibleRootItem())
            item = QTreeWidgetItem([entry.name])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.relative)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, entry.is_dir)
            icon = "folder" if entry.is_dir else "file"
            item.setIcon(0, runtime.icons().get(icon, 13, "muted"))
            item.setToolTip(0, entry.relative)
            parent.addChild(item)
            if entry.is_dir:
                folders[entry.relative] = item
        self.tree.expandToDepth(1)
        self.tree_empty.setVisible(not entries)
        stats = self.projects.stat(self.project)
        size = (
            tr("code.bytes", count=stats["bytes"])
            if stats["bytes"] < 1000
            else tr("code.kilobytes", count=f"{stats['bytes'] / 1000:.1f}")
        )
        self.stats_label.setText(
            tr(
                "code.stats",
                files=stats["files"],
                files_word=tr("code.file_one") if stats["files"] == 1 else tr("code.file_many"),
                folders=stats["folders"],
                folders_word=tr("code.folder_one")
                if stats["folders"] == 1
                else tr("code.folder_many"),
                size=size,
            )
        )
        if self.current_file:
            self._select_in_tree(self.current_file)

    def _select_in_tree(self, relative: str) -> None:
        stack = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if not bool(item.data(0, Qt.ItemDataRole.UserRole + 1)):
                if str(item.data(0, Qt.ItemDataRole.UserRole)) == relative:
                    self.tree.setCurrentItem(item)
                    self.tree.scrollToItem(item)
                    return
            for index in range(item.childCount()):
                stack.append(item.child(index))

    def _update_toolchain_summary(self) -> None:
        items = self.toolchains.detect()
        ready = [item.label for item in items if item.available]
        missing = [item.label for item in items if not item.available]
        # Latin tool names inside a Persian sentence need isolation marks, or
        # the comma jumps to the wrong end of the list when it wraps.
        parts = []
        if ready:
            parts.append(tr("code.toolchains_ready", names="\u2066" + ", ".join(ready) + "\u2069"))
        if missing:
            parts.append(
                tr("code.toolchains_missing", names="\u2066" + ", ".join(missing) + "\u2069")
            )
        self.toolchain_label.setText(" · ".join(parts))
        reasons = "\n".join(
            f"{item.label}: {item.detail}" for item in items if not item.available
        )
        self.toolchain_detail.setText(reasons)
        self.toolchain_label.setToolTip(reasons or "\n".join(
            f"{item.label} {item.version}" for item in items if item.available
        ))
        self.toolchain_toggle.setVisible(bool(reasons))
        if not reasons:
            self.toolchain_detail.setVisible(False)

    def _toggle_toolchain_details(self) -> None:
        visible = not self.toolchain_detail.isVisible()
        self.toolchain_detail.setVisible(visible)
        self.toolchain_toggle.setText(
            tr("code.toolchain_hide") if visible else tr("code.toolchain_details")
        )

    def _on_splitter_moved(self, _position: int, _index: int) -> None:
        self._user_split = True

    def _balance_splitter(self) -> None:
        """Give the editor the room it needs on narrow or high-DPI windows."""
        total = self.top_splitter.width()
        if total <= 0 or self._user_split:
            return
        tree = min(runtime.px(280), max(runtime.px(150), int(total * 0.24)))
        sizes = self.top_splitter.sizes()
        if abs(sizes[0] - tree) <= runtime.px(6):
            return
        self.top_splitter.setSizes([tree, max(runtime.px(160), total - tree)])

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._balance_splitter()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        # A rebuild creates a new splitter with the default sizes; Qt only
        # redistributes once the page has its real width.
        QTimer.singleShot(0, self._balance_splitter)

    def _update_project_ui(self) -> None:
        if self.project is None:
            self.project_label.setText(tr("code.no_project"))
            self.project_label.setToolTip("")
            self.tree_empty.setText(tr("code.no_project_hint"))
            self.tree_empty.setVisible(True)
            for button in (self.new_file_button, self.rename_button, self.delete_button):
                button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.run_button.setEnabled(False)
            self.stats_label.setText("")
            return
        self.project_label.setText(self.project.name)
        self.project_label.setToolTip(self.project.path)
        self.tree_empty.setText(tr("code.empty_project"))
        self.new_file_button.setEnabled(True)
        has_selection = self.tree.currentItem() is not None
        self.rename_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.save_button.setEnabled(self.current_file is not None)
        self.run_button.setEnabled(self.current_file is not None and not self._is_running())

    # -------------------------------------------------------------------- files
    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        self._update_project_ui()
        if bool(item.data(0, Qt.ItemDataRole.UserRole + 1)):
            item.setExpanded(not item.isExpanded())
            return
        self.open_file(str(item.data(0, Qt.ItemDataRole.UserRole)))

    def _on_tree_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if not bool(item.data(0, Qt.ItemDataRole.UserRole + 1)):
            self.open_file(str(item.data(0, Qt.ItemDataRole.UserRole)))

    def _show_tree_menu(self, position) -> None:  # noqa: ANN001
        if self.project is None:
            return
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        new_action = menu.addAction(tr("code.new_file"))
        new_action.triggered.connect(self.new_file)
        if item is not None:
            self.tree.setCurrentItem(item)
            menu.addSeparator()
            if not bool(item.data(0, Qt.ItemDataRole.UserRole + 1)):
                open_action = menu.addAction(tr("code.open"))
                open_action.triggered.connect(
                    lambda: self.open_file(str(item.data(0, Qt.ItemDataRole.UserRole)))
                )
            rename_action = menu.addAction(tr("code.rename"))
            rename_action.triggered.connect(self.rename_selected)
            delete_action = menu.addAction(tr("code.delete_file"))
            delete_action.triggered.connect(self.delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def open_file(self, relative: str) -> None:
        if self.project is None:
            return
        if relative == self.current_file:
            return
        if self._dirty and not self.save_file():
            return
        try:
            content = self.projects.read(self.project, relative)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.current_file = relative
        self.editor.blockSignals(True)
        self.editor.setPlainText(content.text)
        self.editor.blockSignals(False)
        self.editor.set_language(content.language)
        self.editor.setReadOnly(content.binary)
        self.file_label.setText(relative)
        self.file_label.setToolTip(str(self.project.root / relative))
        self.language_badge.setText(content.language.upper())
        self.binary_label.setText(tr("code.binary_warning") if content.binary else "")
        self._update_toolchain_badge(relative)
        self._dirty = False
        self._clean_text = content.text
        self._mark_clean()
        self._select_in_tree(relative)
        self._update_project_ui()
        self.editor.setFocus()

    def save_file(self, quiet: bool = False) -> bool:
        if self.project is None or self.current_file is None:
            return False
        if self.editor.isReadOnly():
            return True
        try:
            content = self.projects.write(
                self.project, self.current_file, self.editor.toPlainText()
            )
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return False
        self._dirty = False
        self._clean_text = self.editor.toPlainText()
        self.language_badge.setText(content.language.upper())
        self._mark_clean()
        if not quiet:
            self._populate_tree()
            self.notify.emit(tr("code.saved_toast", name=self.current_file), "success")
        return True

    def new_file(self) -> None:
        if self.project is None:
            self.notify.emit(tr("code.open_first"), "warning")
            return
        name, ok = QInputDialog.getText(self, tr("code.new_file"), tr("code.file_name"))
        name = (name or "").strip()
        if not ok or not name:
            return
        try:
            self.projects.create_file(self.project, name, "")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self._populate_tree()
        self.open_file(name)
        self._populate_tree()

    def rename_selected(self) -> None:
        if self.project is None:
            return
        item = self.tree.currentItem()
        if item is None:
            self.notify.emit(tr("code.select_file_first"), "warning")
            return
        relative = str(item.data(0, Qt.ItemDataRole.UserRole))
        name, ok = QInputDialog.getText(
            self, tr("code.rename"), tr("code.file_name"), text=item.text(0)
        )
        name = (name or "").strip()
        if not ok or not name or name == item.text(0):
            return
        try:
            new_relative = self.projects.rename(self.project, relative, name)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        if self.current_file == relative or self.current_file == new_relative:
            self.current_file = new_relative
            self.file_label.setText(new_relative)
            self._update_toolchain_badge(new_relative)
        self._populate_tree()
        self._update_project_ui()

    def delete_selected(self) -> None:
        if self.project is None:
            return
        item = self.tree.currentItem()
        if item is None:
            self.notify.emit(tr("code.select_file_first"), "warning")
            return
        relative = str(item.data(0, Qt.ItemDataRole.UserRole))
        try:
            self.projects.delete(self.project, relative)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        if self.current_file == relative:
            self.current_file = None
            self.editor.blockSignals(True)
            self.editor.clear()
            self.editor.blockSignals(False)
            self.editor.setReadOnly(False)
            self.file_label.setText(tr("code.no_file"))
            self.language_badge.setText("—")
            self.toolchain_badge.setText(tr("code.no_toolchain"))
        self._dirty = False
        self._clean_text = ""
        self.dirty_label.setText("")
        self._populate_tree()
        self._update_project_ui()
        self.notify.emit(tr("code.deleted_toast", name=relative), "info")

    # ------------------------------------------------------------------ editor
    def _on_text_changed(self) -> None:
        if self.current_file is None or self.editor.isReadOnly():
            return
        # A syntax re-highlight also emits textChanged in Qt, so never trust the
        # signal alone: compare with the text that is actually on disk.
        modified = self.editor.toPlainText() != self._clean_text
        if modified and not self._dirty:
            self._dirty = True
            self._mark_dirty()
        elif not modified and self._dirty:
            self._dirty = False
            self._mark_clean()
        if modified and bool(self.context.settings.get("ui.editor_autosave", True)):
            self._autosave.start()
        self._update_cursor_label()

    def _autosave_tick(self) -> None:
        if self._dirty and self.current_file and not self._is_running():
            self.save_file(quiet=True)

    def _mark_dirty(self) -> None:
        self._repolish_label(self.dirty_label, tr("code.unsaved"), "warning")

    def _mark_clean(self) -> None:
        self.dirty_label.setVisible(False)
        self.dirty_label.setText("")
        self.setWindowModified(False)

    @staticmethod
    def _repolish_label(label: QLabel, text: str, role: str) -> None:
        label.setVisible(True)
        label.setText(text)
        label.setProperty("role", role)
        label.style().unpolish(label)
        label.style().polish(label)

    def _update_cursor_label(self) -> None:
        cursor = self.editor.textCursor()
        self.cursor_label.setText(
            tr("code.cursor", line=cursor.blockNumber() + 1, column=cursor.columnNumber() + 1)
        )

    def _update_toolchain_badge(self, relative: str) -> None:
        chain = self.toolchains.for_extension(Path(relative).suffix.lower())
        if chain is None:
            self.toolchain_badge.setText(tr("code.no_toolchain"))
            self.toolchain_badge.setToolTip(tr("code.no_runner_hint"))
            return
        if chain.available:
            version = (chain.version or "").strip()
            short = version.split()[-1] if version.split() else ""
            self.toolchain_badge.setText(f"{chain.label} {short}".strip())
            self.toolchain_badge.setToolTip(version)
            self.toolchain_badge.set_tone("violet")
        else:
            self.toolchain_badge.setText(tr("code.toolchain_missing", name=chain.label))
            self.toolchain_badge.setToolTip(chain.detail)
            self.toolchain_badge.set_tone("warning")

    # --------------------------------------------------------------------- run
    def _is_running(self) -> bool:
        return self._run_thread is not None and self._run_thread.is_alive()

    def run_current(self) -> None:
        if self.project is None or self.current_file is None or self._is_running():
            return
        if not self.save_file(quiet=True):
            return
        source = self.project.root / self.current_file
        timeout = float(self.context.settings.get("code.timeout_seconds", 10.0) or 10.0)
        try:
            plan = self.runner.plan_for(source, cwd=self.project.root, timeout_seconds=timeout)
        except ToolchainUnavailable as exc:
            self._show_unavailable(exc)
            return
        self.clear_output()
        self.command_label.setText(plan.command)
        self._set_running(True)
        bridge = self._bridge
        cancel = threading.Event()
        self._cancel_event = cancel

        def work() -> None:
            try:
                result = self.runner.run(
                    plan,
                    on_output=lambda stream, line: bridge.output.emit(stream, line),
                    cancel_event=cancel,
                )
            except Exception as exc:  # noqa: BLE001 - surface, never die silently
                result = RunResult(plan=plan)
                bridge.output.emit("stderr", f"[error] {exc}")
            bridge.finished.emit(result)

        self._run_thread = threading.Thread(target=work, name="myai-code-run", daemon=True)
        self._run_thread.start()

    def _show_unavailable(self, exc: ToolchainUnavailable) -> None:
        self.clear_output()
        self._append_output("stderr", tr("code.unavailable_title"))
        self._append_output("stderr", exc.detail)
        self.status_badge.setText(tr("code.unavailable_badge"))
        self.status_badge.set_tone("warning")
        self.notify.emit(tr("code.unavailable_notice", detail=exc.detail), "warning")

    def stop_run(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.status_badge.setText(tr("code.stopping"))

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running and self.current_file is not None)
        self.stop_button.setEnabled(running)
        self.open_button.setEnabled(not running)
        self.new_project_button.setEnabled(not running)
        self.tree.setEnabled(not running)

    def _on_output(self, stream: str, text: str) -> None:
        self._append_output(stream, text)

    def _append_output(self, stream: str, text: str) -> None:
        colors = {
            "stdout": runtime.theme().color("text"),
            "stderr": runtime.theme().color("danger"),
            "system": runtime.theme().color("text_faint"),
        }
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.output_view.append(
            f'<span style="color:{colors.get(stream, colors["stdout"])};'
            f' white-space:pre-wrap;">{safe}</span>'
        )
        bar = self.output_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_output(self) -> None:
        self.output_view.clear()
        self.command_label.setText("")
        self.status_badge.setText(tr("code.not_run"))
        self.status_badge.set_tone("muted")

    def _on_run_finished(self, result: RunResult) -> None:
        self._set_running(False)
        self._run_thread = None
        self._cancel_event = None
        if result.status == "ok":
            self.status_badge.set_tone("success")
            self.status_badge.setText(
                tr("code.status_ok", code=result.exit_code, ms=result.duration_ms)
            )
        elif result.status == "timeout":
            self.status_badge.set_tone("warning")
            self.status_badge.setText(
                tr("code.status_timeout", seconds=int(result.plan.timeout_seconds))
            )
        elif result.status == "cancelled":
            self.status_badge.set_tone("warning")
            self.status_badge.setText(tr("code.status_cancelled"))
        else:
            code = result.exit_code if result.exit_code is not None else "?"
            self.status_badge.set_tone("danger")
            self.status_badge.setText(tr("code.status_failed", code=code, ms=result.duration_ms))
        if result.truncated:
            self._append_output("system", tr("code.output_truncated"))
        if result.stdout == "" and result.stderr == "":
            self._append_output("system", tr("code.no_output"))
        self.context.activity.record(
            key="code.activity_run", kwargs={"name": self.current_file or "?"}, kind="code"
        )
        self._update_project_ui()

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        super().retranslate()
        self.setAccessibleName(tr("code.title"))
        self.open_button.setText(tr("code.open_folder"))
        self.new_project_button.setText(tr("code.new_project"))
        self.save_button.setText(tr("code.save"))
        self.run_button.setText(tr("code.run"))
        self.stop_button.setText(tr("code.stop"))
        self.clear_button.setText(tr("code.clear"))
        self.project_select.set_placeholder(tr("code.recent_projects"))
        self.editor.setPlaceholderText(tr("code.editor_hint"))
        self.new_file_button.setAccessibleName(tr("code.new_file"))
        self.new_file_button.setToolTip(tr("code.new_file"))
        self.rename_button.setAccessibleName(tr("code.rename"))
        self.rename_button.setToolTip(tr("code.rename"))
        self.delete_button.setAccessibleName(tr("code.delete_file"))
        self.delete_button.setToolTip(tr("code.delete_file"))
        if self.current_file is None:
            self.file_label.setText(tr("code.no_file"))
        if self.project is None:
            self.project_label.setText(tr("code.no_project"))
            self.tree_empty.setText(tr("code.no_project_hint"))
        else:
            self.tree_empty.setText(tr("code.empty_project"))
        if self.status_badge.text() == tr("code.not_run") or not self.output_view.toPlainText():
            self.status_badge.setText(tr("code.not_run"))
        self.toolchain_toggle.setText(
            tr("code.toolchain_hide")
            if self.toolchain_detail.isVisible()
            else tr("code.toolchain_details")
        )
        self._update_toolchain_summary()
        self._update_cursor_label()

    def refresh(self) -> None:
        """Called when the page becomes visible and after a rebuild."""
        self._refresh_recent()
        if self.project is not None:
            self._populate_tree()
            self._update_toolchain_summary()
        self._update_project_ui()

    def refresh_theme(self) -> None:
        self.editor.refresh_theme()
        self._update_cursor_label()
        self.update()

    def rebuild(self) -> None:
        """Keep the open project, file and unsaved text across a rebuild."""
        project = self.project
        relative = self.current_file
        pending = self.editor.toPlainText() if self._dirty else None
        self._autosave.stop()
        super().rebuild()
        # A direction/theme change recreates the FlowLayout; drop the stale one
        # so the direction hook cannot touch a deleted C++ object.
        if self.actions_flow is not None:
            self.actions_flow.invalidate()
        if project is not None:
            self.project = project
            self._populate_tree()
        if relative:
            self.current_file = relative
            try:
                content = self.projects.read(project, relative)
            except Exception:  # noqa: BLE001 - file vanished, keep the page usable
                content = None
            if content is not None:
                self.editor.blockSignals(True)
                self.editor.setPlainText(pending if pending is not None else content.text)
                self.editor.blockSignals(False)
                self.editor.set_language(content.language)
                self.editor.setReadOnly(content.binary)
                self.file_label.setText(relative)
                self.language_badge.setText(content.language.upper())
                self._update_toolchain_badge(relative)
                self._clean_text = content.text
                if pending is not None and pending != content.text:
                    self._dirty = True
                    self._mark_dirty()
                else:
                    self._dirty = False
                    self._mark_clean()
        self._update_project_ui()
        self._refresh_recent()
        QTimer.singleShot(0, self._balance_splitter)

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        self._autosave.stop()
        if self._dirty and self.current_file:
            self.save_file(quiet=True)
        if self._cancel_event is not None:
            self._cancel_event.set()
        thread = self._run_thread
        if thread is not None:
            thread.join(timeout=3)
