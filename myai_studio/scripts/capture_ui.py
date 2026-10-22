"""Capture the full UI state matrix for visual review and phase evidence.

Produces one PNG per (language × theme × sidebar state) plus dialogs and routes,
all rendered from the real application window. Output goes to ``artifacts/ui``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from myai.context import build_context  # noqa: E402
from myai.i18n import tr  # noqa: E402
from myai.services.backup import BackupService  # noqa: E402
from myai.services.openrouter import (  # noqa: E402
    ChatResult,
    StreamStats,
    ToolCall,
    model_to_dict,
    parse_model,
)
from myai.ui.main_window import MainWindow  # noqa: E402
from myai.ui.theme import runtime  # noqa: E402
from myai.ui.theme.manager import ThemeManager  # noqa: E402
from myai.ui.views.settings_dialog import SettingsDialog  # noqa: E402
from myai.ui.widgets.dialogs import ConfirmDialog  # noqa: E402

SAMPLE_ASSISTANT = """## A plan that actually runs

1. **Define the contract** — one file, one purpose.
2. **Run it for real** — never trust a screenshot.

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

| Stage | Tool | Real output |
| --- | --- | --- |
| Build | gcc / python | captured |
| Test | pytest | 42 passed |

> A calm interface is not a decoration; it is a promise that the machine will
> not waste your attention."""


def seed(ctx) -> None:  # noqa: ANN001
    service = ctx.conversations
    folder = service.create_folder("Product research")
    first = service.create("Redesigning the onboarding flow", select=False)
    service.add_message(first.id, "user", "How would you restructure onboarding for a local-first AI app?")
    service.add_message(first.id, "assistant", SAMPLE_ASSISTANT)
    second = service.create("Compiler sandbox notes", select=False, folder_id=folder.id)
    service.add_message(second.id, "user", "Draft a safe sandbox policy for running generated C code.")
    service.add_message(second.id, "assistant",
                        "Use a jailed working directory, a wall-clock limit of ten seconds, "
                        "and never install packages without approval.")
    third = service.create("Weekly synthesis", select=False)
    service.add_message(third.id, "user", "Summarise what we learned this week.")
    service.add_message(third.id, "assistant", "Three themes: clarity beats cleverness, measurements beat guesses.")
    service.set_pinned(third.id, True)

    # Phase 2 surfaces get real local data so the screenshots show true state.
    ctx.memory.add("Works primarily in Python and TypeScript.", scope="global")
    ctx.memory.add("Prefers short answers with the code first.", scope="global", pinned=True)
    ctx.memory.add(
        "This thread is about jailing generated C code.",
        scope="conversation",
        conversation_id=second.id,
    )
    ctx.persona.write_profile(
        "# دربارهٔ من\n\n- نام: نیما\n- نقش: مهندس بک‌اند\n"
        "- زبان ترجیحی پاسخ: فارسی\n- حوزهٔ تخصص: کامپایلر و ابزار توسعه\n"
    )
    ctx.persona.save(
        enabled=True,
        text="پاسخ‌ها کوتاه و فنی باشند؛ هر جا محدودیت واقعی وجود دارد، صریح بگو.",
        tone="precise",
        detail="balanced",
        language="fa",
    )
    artifact = ctx.outputs.create(
        "sandbox_policy.py",
        'import resource\nimport subprocess\n\n\ndef run(path: str) -> int:\n'
        '    """Run generated code with a hard wall-clock limit."""\n'
        '    return subprocess.call(["python", path], timeout=10)\n',
        conversation_id=second.id,
    )
    ctx.outputs.update(
        artifact.id,
        content='import resource\nimport subprocess\n\n\ndef run(path: str, seconds: int = 10) -> int:\n'
        '    """Run generated code with a hard wall-clock and memory limit."""\n'
        '    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))\n'
        '    return subprocess.call(["python", path], timeout=seconds)\n',
        note="raise limits",
    )


    # Phase 5 surfaces: real prompt rows, real task rows, real files on disk.
    ctx.tasks.record(
        kind="agent",
        title="Explain what hello.py prints",
        status="ok",
        detail="hello.py prints a greeting and exits with code 0.",
        model_id="capture/tool-model",
        project=str(ctx.paths.projects_dir / "phase3-demo"),
        tool_count=1,
        duration_ms=2400,
        steps=[
            {"index": 1, "kind": "tool", "text": "read_file hello.py",
             "tool": "read_file", "ok": True, "error": ""},
            {"index": 2, "kind": "final", "text": "hello.py prints a greeting.",
             "tool": "", "ok": True, "error": ""},
        ],
    )
    ctx.tasks.record(
        kind="code",
        title="python hello.py",
        status="ok",
        detail="Hello, world!\nHello, code studio!",
        project=str(ctx.paths.projects_dir / "phase3-demo"),
        duration_ms=420,
    )
    ctx.tasks.record(
        kind="agent",
        title="Rename the sandbox module",
        status="cancelled",
        detail="Stopped by the user after the first step.",
        model_id="capture/tool-model",
        tool_count=1,
        duration_ms=1300,
    )
    ctx.plugins.write_example()
    ctx.plugins.set_enabled("example-prompt-pack", True)


DEMO_FILES = {
    "hello.py": (
        "def greet(name: str) -> str:\n"
        "    return f\"Hello, {name}!\"\n\n\n"
        "for who in (\"world\", \"code studio\"):\n"
        "    print(greet(who))\n"
    ),
    "fib.py": (
        "def fib(n: int) -> int:\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a\n\n\n"
        "print([fib(i) for i in range(10)])\n"
    ),
    "broken.c": (
        "#include <stdio.h>\n\n"
        "int main(void) {\n"
        "    printf(\"never runs\\n\");\n"
        "    retrun 0;\n"
        "}\n"
    ),
    "Hello.java": "class Hello {\n    public static void main(String[] args) {\n        System.out.println(\"hi\");\n    }\n}\n",
    "notes.md": "# Project notes\n\n- run `hello.py` to see real stdout\n- C files compile into `.myai-build`\n",
    "app.js": "const values = [1, 2, 3];\nconsole.log(values.map((v) => v * 2).join(','));\n",
}


class CaptureAgentClient:
    """Deterministic stand-in for the provider (no live key in this sandbox).

    It answers with one real ``read_file`` call and a fixed summary so the
    timeline can be captured from real tool execution. The capture is labelled
    as a test double in the report; it is never presented as a live model reply.
    """

    def __init__(self, path: str = "hello.py") -> None:
        self.path = path
        self.calls = 0

    def stream_chat(self, **_kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        if self.calls % 2 == 1:
            return ChatResult(
                stats=StreamStats(finish_reason="tool_calls", total_tokens=21),
                tool_calls=[ToolCall(id=f"capture-{self.calls}", name="read_file",
                                     arguments=json.dumps({"path": self.path}))],
            )
        return ChatResult(
            text=(
                "hello.py prints a Persian and an English greeting, then exits with "
                "code 0. No other file was touched."
            ),
            stats=StreamStats(total_tokens=48, completion_tokens=26),
        )


def build_demo_project(ctx) -> Path:  # noqa: ANN001
    root = ctx.paths.projects_dir / "phase3-demo"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in DEMO_FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "greet.py").write_text(
        "from pathlib import Path\n\nprint('submodule ok:', Path(__file__).name)\n", encoding="utf-8"
    )
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "ui"))
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--only",
        default="",
        help="write only screenshots whose name contains this text (e.g. p4_agent)",
    )
    args = parser.parse_args()
    only = args.only.strip()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("[capture] workspace", flush=True)
    home = Path(tempfile.mkdtemp(prefix="myai-ui-"))
    ctx = build_context(home, log=False)
    ctx.boot()
    print("[capture] booted", flush=True)
    seed(ctx)
    demo = build_demo_project(ctx)
    print("[capture] seeded", flush=True)

    app = QApplication(sys.argv[:1])
    theme = ThemeManager(app, ctx.settings, ctx.paths)
    runtime.set_manager(theme)
    theme.apply()
    window = MainWindow(ctx, theme)
    window.resize(1440, 900)
    print("[capture] window built", flush=True)
    window.show()
    app.processEvents()
    print("[capture] window shown", flush=True)

    written: list[str] = []

    def render(widget: QWidget, path: Path) -> None:
        """Render a widget tree synchronously; avoids stale backing stores."""
        widget.repaint()
        app.processEvents()
        pixmap = QPixmap(widget.size())
        pixmap.fill(0)
        widget.render(pixmap)
        pixmap.save(str(path))
        written.append(str(path))

    def shot(name: str) -> None:
        if only and only not in name:
            return
        # Toasts are transient; keep them out of the evidence frames.
        window.toasts.clear()
        app.processEvents()
        render(window, out / f"{name}.png")

    def dialog_shot(dialog: QWidget, name: str) -> None:
        if only and only not in name:
            return
        dialog.show()
        app.processEvents()
        pixmap = QPixmap(dialog.size())
        # Keep the dialog's own translucency: the card and its shadow are drawn
        # over the dimmed window instead of a solid black slab.
        pixmap.fill(QColor(0, 0, 0, 0))
        dialog.render(pixmap)
        combined = QPixmap(window.size())
        combined.fill(0)
        window.render(combined)
        from PySide6.QtGui import QPainter

        painter = QPainter(combined)
        # Dim the whole window, exactly like the real modal backdrop does; the
        # dialog pixmap alone would leave a grey rectangle floating in the frame.
        painter.fillRect(combined.rect(), QColor(0, 0, 0, 130))
        painter.drawPixmap(dialog.mapTo(window, dialog.rect().topLeft()), pixmap)
        painter.end()
        combined.save(str(out / f"{name}.png"))
        written.append(str(out / f"{name}.png"))
        dialog.reject()
        app.processEvents()

    conversation = next(c for c in ctx.conversations.list() if c.title.startswith("Compiler"))
    steps: list = []

    def step(fn) -> None:  # noqa: ANN001
        steps.append(fn)

    # 1. Welcome, both languages and themes
    for language in ("fa", "en"):
        for theme_key in ("midnight", "dawn"):
            step(lambda lang=language, t=theme_key: ctx.settings.update({"ui.language": lang, "ui.theme": t}))
            step(lambda lang=language, t=theme_key: shot(f"01_welcome_{t}_{lang}"))

    # 2. Conversation with a real thread, sidebar open and collapsed
    step(lambda: ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"}))
    step(lambda: window.open_conversation(conversation.id))
    step(lambda: shot("02_conversation_dark_fa"))
    step(lambda: window.sidebar.set_collapsed(True, animate=False))
    step(lambda: app.processEvents())
    step(lambda: shot("03_sidebar_collapsed_fa"))
    step(lambda: window.sidebar.set_collapsed(False, animate=False))
    step(lambda: app.processEvents())

    # 3. Same conversation in the other three language/theme combinations
    for theme_key in ("dawn", "aurora"):
        step(lambda t=theme_key: ctx.settings.update({"ui.theme": t, "ui.language": "fa"}))
        step(lambda t=theme_key: shot(f"04_conversation_{t}_fa"))
    step(lambda: ctx.settings.update({"ui.theme": "midnight", "ui.language": "en"}))
    step(lambda: app.processEvents())
    step(lambda: shot("05_conversation_dark_en"))

    # 4. Code Studio on the real demo project (Phase 3 replaced the placeholder)
    page = window.code_page

    def open_demo(name: str) -> None:
        page.set_project(page.projects.open_folder(demo))
        page.open_file(name)

    def run_demo() -> None:
        page.run_current()
        deadline = time.monotonic() + 25
        while page._is_running() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    step(lambda: window._navigate("code"))
    step(lambda: open_demo("hello.py"))
    step(run_demo)
    step(lambda: shot("06_code_studio_run_en"))
    step(lambda: window._go_chat())
    step(lambda: app.processEvents())

    # 5. Window sizes
    for width, height in ((1280, 720), (1920, 1080)):
        step(lambda w=width, h=height: window.resize(w, h))
        step(lambda w=width, h=height: shot(f"07_size_{w}x{h}_en"))
    step(lambda: window.resize(1440, 900))
    step(lambda: ctx.settings.set("ui.language", "fa"))
    step(lambda: app.processEvents())

    # 6. Dialogs
    def confirm() -> None:
        dialog = ConfirmDialog(
            window,
            "حذف گفتگو؟",
            "«Redesigning the onboarding flow» و همهٔ پیام‌های آن از این دستگاه حذف می‌شود. این کار بازگشت‌پذیر نیست.",
            confirm_text="حذف",
            cancel_text="انصراف",
            danger=True,
            icon="trash",
        )
        dialog_shot(dialog, "08_confirm_dialog_fa")

    def settings_dialog() -> None:
        dialog = SettingsDialog(
            window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets,
            BackupService(ctx.paths, ctx.db, ctx.settings), initial="appearance",
        )
        dialog_shot(dialog, "09_settings_appearance_fa")

    def settings_language() -> None:
        dialog = SettingsDialog(
            window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets,
            BackupService(ctx.paths, ctx.db, ctx.settings), initial="language",
        )
        dialog_shot(dialog, "10_settings_language_fa")

    # 7. Phase 2 pages: every route, both languages, dark and light.
    for language in ("fa", "en"):
        for theme_key in ("midnight", "dawn"):
            for route in ("api", "memory", "persona", "studio"):
                step(lambda lang=language, t=theme_key: ctx.settings.update(
                    {"ui.language": lang, "ui.theme": t}))
                step(lambda r=route: window._navigate(r))
                step(lambda: app.processEvents())
                step(lambda r=route, lang=language, t=theme_key: shot(f"p2_{r}_{t}_{lang}"))

    # 7b. Phase 3 Code Studio: real project, real run, both languages/themes.
    for language in ("fa", "en"):
        for theme_key in ("midnight", "dawn"):
            step(lambda lang=language, t=theme_key: ctx.settings.update(
                {"ui.language": lang, "ui.theme": t}))
            step(lambda: window._navigate("code"))
            step(lambda: open_demo("hello.py"))
            step(run_demo)
            step(lambda lang=language, t=theme_key: shot(f"p3_code_{t}_{lang}"))

    # 7c. Compiler error, verbatim from gcc.
    step(lambda: ctx.settings.update({"ui.language": "en", "ui.theme": "dawn"}))
    step(lambda: window._navigate("code"))
    step(lambda: open_demo("broken.c"))
    step(run_demo)
    step(lambda: shot("p3_code_compile_error_dawn_en"))

    # 7d. Missing toolchain: the page must name javac instead of faking a run.
    step(lambda: ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"}))
    step(lambda: window._navigate("code"))
    step(lambda: open_demo("Hello.java"))
    step(lambda: page._toggle_toolchain_details())
    step(run_demo)
    step(lambda: shot("p3_code_unavailable_midnight_fa"))

    # 7e. Agent Mode (Phase 4). The workspace gets a placeholder key and a
    # deterministic client so the page can be captured mid-run; the report says
    # plainly that no live model call happened here.
    agent_page = window.agent_page
    original_factory = ctx.chat._client_factory  # noqa: SLF001 - capture-only seam
    tool_models = [
        parse_model({"id": "capture/tool-model", "name": "Capture Tool Model",
                     "supported_parameters": ["tools", "temperature"]}),
    ]
    ctx.settings.update({
        "ai.openrouter_cache": [model_to_dict(model) for model in tool_models],
        "ai.default_model": "capture/tool-model",
    })
    ctx.secrets.set_api_key("sk-or-v1-capture-placeholder")

    def install_capture_client() -> None:
        client = CaptureAgentClient()
        ctx.chat._client_factory = lambda: client  # noqa: SLF001
        agent_page.task_edit.setPlainText("Read hello.py and summarise what it does.")
        agent_page._update_controls()

    def run_agent() -> None:
        install_capture_client()
        agent_page.start()
        deadline = time.monotonic() + 20
        while agent_page._thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    def reset_agent_view() -> None:
        """Start each language/theme frame from an empty timeline."""
        agent_page._run = None
        agent_page._clear_timeline()
        ctx.agent._history.clear()  # noqa: SLF001 - capture-only reset
        agent_page._refresh_runs()
        agent_page.status_badge.setText(tr("agent.status_idle"))
        agent_page.status_badge.set_tone("muted")
        agent_page._update_controls()

    for language in ("fa", "en"):
        for theme_key in ("midnight", "dawn"):
            step(lambda lang=language, t=theme_key: ctx.settings.update(
                {"ui.language": lang, "ui.theme": t}))
            step(lambda: window._navigate("agent"))
            step(reset_agent_view)
            step(lambda: app.processEvents())
            step(lambda lang=language, t=theme_key: shot(f"p4_agent_idle_{t}_{lang}"))
            step(run_agent)
            step(lambda lang=language, t=theme_key: shot(f"p4_agent_run_{t}_{lang}"))

    def agent_approval() -> None:
        ctx.settings.update({"ui.language": "en", "ui.theme": "dawn"})
        theme.apply()
        window._navigate("agent")
        window.repaint()
        app.processEvents()
        dialog = ConfirmDialog(
            window,
            tr("agent.approve_title"),
            tr("agent.approve_body").format(
                tool=tr("agent.tool_write_file"),
                arguments=json.dumps({"path": "hello.py", "content": "print('hi')\\n"},
                                     ensure_ascii=False, indent=2),
            ),
            confirm_text=tr("agent.approve"),
            cancel_text=tr("agent.deny"),
            danger=True,
            icon="shield",
        )
        dialog_shot(dialog, "p4_agent_approve_dawn_en")

    step(agent_approval)

    def agent_settings() -> None:
        ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"})
        app.processEvents()
        dialog = SettingsDialog(
            window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets,
            BackupService(ctx.paths, ctx.db, ctx.settings), initial="agent",
        )
        dialog_shot(dialog, "10b_settings_agent_fa")

    step(agent_settings)

    def settings_ai() -> None:
        """The AI page: provider status plus a temperature slider that is real."""
        ctx.settings.update({"ui.language": "en", "ui.theme": "dawn"})
        app.processEvents()
        dialog = SettingsDialog(
            window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets,
            BackupService(ctx.paths, ctx.db, ctx.settings), initial="ai",
        )
        dialog_shot(dialog, "11_settings_ai_p5_en")

    def settings_memory() -> None:
        """The memory page: a real count from the database, not a promise."""
        ctx.memory.add("The user prefers short answers in Persian.", scope="global")
        ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"})
        app.processEvents()
        dialog = SettingsDialog(
            window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets,
            BackupService(ctx.paths, ctx.db, ctx.settings), initial="memory",
        )
        dialog_shot(dialog, "12_settings_memory_p5_fa")

    step(settings_ai)
    step(settings_memory)

    def drop_capture_credentials() -> None:
        ctx.secrets.set_api_key("")
        ctx.chat._client_factory = original_factory  # noqa: SLF001
        window._navigate("agent")
        app.processEvents()

    step(drop_capture_credentials)

    # 7f. Phase 5: the seven library pages, fa RTL and en LTR.
    def write_sample_image() -> None:
        from PySide6.QtGui import QImage

        image = QImage(320, 200, QImage.Format.Format_ARGB32)
        image.fill(QColor("#7aa2ff"))
        image.save(str(ctx.paths.images_dir / "dawn-moodboard.png"))

    step(write_sample_image)
    step(lambda: (ctx.paths.videos_dir / "walkthrough.mp4").write_bytes(b"\x00" * 4096))
    for language in ("fa", "en"):
        for theme_key in ("midnight", "dawn"):
            step(lambda lang=language, t=theme_key: ctx.settings.update(
                {"ui.language": lang, "ui.theme": t}))
            for route in ("prompts", "tasks", "performance", "images", "video", "web", "plugins"):
                step(lambda r=route: window._navigate(r))
                step(lambda: app.processEvents())
                step(lambda r=route, lang=language, t=theme_key: shot(
                    f"p5_{r}_{t}_{lang}"))

    def prompt_dialog() -> None:
        from myai.ui.views.prompts_page import PromptEditor

        entry = next(e for e in ctx.prompts.list() if e.title.startswith("Review"))
        dialog = PromptEditor(window, entry=entry, categories=ctx.prompts.categories())
        dialog_shot(dialog, "p5_prompt_editor_dawn_en")

    step(lambda: ctx.settings.update({"ui.language": "en", "ui.theme": "dawn"}))
    step(lambda: window._navigate("prompts"))
    step(lambda: app.processEvents())
    step(prompt_dialog)
    step(lambda: ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"}))
    step(lambda: window._navigate("prompts"))
    step(lambda: app.processEvents())

    # 7g. After Phase 5: real attachment chips and the command palette.
    demo_files = Path(ctx.paths.home) / "demo-files"

    def attach_demo_files() -> None:
        demo_files.mkdir(parents=True, exist_ok=True)
        (demo_files / "release-notes.md").write_text(
            "# Release 0.5\n\n- file attachments\n- command palette\n- Windows 11 rules\n",
            encoding="utf-8",
        )
        (demo_files / "sandbox_policy.py").write_text(
            "def run(path: str) -> int:\n    return 0\n", encoding="utf-8"
        )
        window.new_chat()
        for name in ("release-notes.md", "sandbox_policy.py"):
            window.composer._add_attachment(str(demo_files / name))
        app.processEvents()

    step(lambda: ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"}))
    step(attach_demo_files)
    step(lambda: shot("attach_chips_midnight_fa"))

    def attachment_preview() -> None:
        from myai.ui.widgets.dialogs import PreviewDialog

        record = ctx.attachments.ingest(demo_files / "release-notes.md")
        dialog = PreviewDialog(
            window,
            title=record.name,
            subtitle=f"{record.kind} · {record.size} bytes · {record.chars} characters",
            text=record.text,
        )
        dialog_shot(dialog, "attach_preview_dawn_en")

    step(lambda: ctx.settings.update({"ui.language": "en", "ui.theme": "dawn"}))
    step(attachment_preview)

    def palette_dialog() -> None:
        from myai.ui.widgets.palette import CommandPalette

        dialog = CommandPalette(window, window._palette_actions())
        dialog.show()
        app.processEvents()
        dialog_shot(dialog, "palette_dawn_en")

    step(lambda: window._navigate("chat"))
    step(lambda: app.processEvents())
    step(palette_dialog)
    step(lambda: ctx.settings.update({"ui.language": "fa", "ui.theme": "midnight"}))

    # 8. DPI / minimum-window stress / minimum-window stress: 1.25x and 1.5x font scale at 1120x720.
    for scale in (1.25, 1.5):
        step(lambda sc=scale: ctx.settings.update({"ui.font_scale": sc}))
        step(lambda: window.resize(runtime.px(1120 * 1.0), runtime.px(720 * 1.0)))
        # Without this the DPI shots inherited the last route of the loop above
        # and the "api" file actually showed Output Studio.
        step(lambda: window._navigate("api"))
        step(lambda: app.processEvents())
        step(lambda sc=scale: shot(f"p2_scale_{str(sc).replace('.', '_')}_api_en"))
        step(lambda: window._navigate("studio"))
        step(lambda: app.processEvents())
        step(lambda sc=scale: shot(f"p2_scale_{str(sc).replace('.', '_')}_studio_en"))
        step(lambda: ctx.settings.update({"ui.language": "en"}))
        step(lambda: window._navigate("code"))
        step(lambda: open_demo("hello.py"))
        step(run_demo)
        step(lambda sc=scale: shot(f"p3_scale_{str(sc).replace('.', '_')}_code_en"))
        step(lambda: window._navigate("agent"))
        step(lambda: app.processEvents())
        step(lambda sc=scale: shot(f"p4_agent_scale_{str(sc).replace('.', '_')}_en"))
    step(lambda: ctx.settings.update({"ui.font_scale": 1.0}))
    step(lambda: window.resize(1440, 900))
    step(lambda: ctx.settings.update({"ui.theme": "midnight", "ui.language": "fa"}))
    step(lambda: app.processEvents())

    step(confirm)
    step(settings_dialog)
    step(settings_language)

    def done() -> None:
        app.quit()

    steps.append(done)

    index = {"i": 0}

    def run_next() -> None:
        if index["i"] >= len(steps):
            app.quit()
            return
        fn = steps[index["i"]]
        index["i"] += 1

        def call() -> None:
            try:
                print(f"[capture] step {index['i']}/{len(steps)}", flush=True)
                fn()
            except Exception:
                import traceback

                traceback.print_exc()
            finally:
                QTimer.singleShot(60, run_next)

        QTimer.singleShot(40, call)

    QTimer.singleShot(80, run_next)
    app.exec()
    print("\n".join(written))
    ctx.shutdown()
    if not args.keep:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
