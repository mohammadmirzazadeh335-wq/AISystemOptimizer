"""Capture the full UI state matrix for visual review and phase evidence.

Produces one PNG per (language × theme × sidebar state) plus dialogs and routes,
all rendered from the real application window. Output goes to ``artifacts/ui``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from myai.context import build_context  # noqa: E402
from myai.services.backup import BackupService  # noqa: E402
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "ui"))
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("[capture] workspace", flush=True)
    home = Path(tempfile.mkdtemp(prefix="myai-ui-"))
    ctx = build_context(home, log=False)
    ctx.boot()
    print("[capture] booted", flush=True)
    seed(ctx)
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
        # Toasts are transient; keep them out of the evidence frames.
        window.toasts.clear()
        app.processEvents()
        render(window, out / f"{name}.png")

    def dialog_shot(dialog: QWidget, name: str) -> None:
        dialog.show()
        app.processEvents()
        pixmap = QPixmap(dialog.size())
        pixmap.fill(0)
        dialog.render(pixmap)
        combined = QPixmap(window.size())
        combined.fill(0)
        window.render(combined)
        from PySide6.QtGui import QPainter

        painter = QPainter(combined)
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

    # 4. A phase-locked route
    step(lambda: window._navigate("code"))
    step(lambda: shot("06_route_code_en"))
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

    # 8. DPI / minimum-window stress: 1.25x and 1.5x font scale at 1120x720.
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
