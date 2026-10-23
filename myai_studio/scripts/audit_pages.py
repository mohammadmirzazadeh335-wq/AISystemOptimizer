"""One screenshot per page: the quick visual audit for a UI polish pass.

Unlike ``capture_ui.py`` (the full state matrix) this script boots the real
window, seeds a small but realistic workspace and renders every AI route once,
so a change to the shared chrome can be reviewed across all pages in one run.

Usage::

    QT_QPA_PLATFORM=offscreen python scripts/audit_pages.py [--out DIR] [--lang en]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy import update  # noqa: E402

from myai.context import build_context  # noqa: E402
from myai.data.models import Message  # noqa: E402
from myai.ui.main_window import AI_ROUTES, MainWindow  # noqa: E402
from myai.ui.theme import runtime  # noqa: E402
from myai.ui.theme.manager import ThemeManager  # noqa: E402

PROJECT_FILES = {
    "main.py": (
        "from src.engine import Engine\nfrom src.config import load\n\n\n"
        "def main() -> int:\n    engine = Engine(load('demo.toml'))\n    return engine.run()\n"
    ),
    "src/__init__.py": "",
    "src/engine.py": (
        "from .config import Config\nfrom . import utils\n\n\n"
        "class Engine:\n    def __init__(self, config: Config) -> None:\n"
        "        self.config = config\n\n    def run(self) -> int:\n        return utils.now()\n"
    ),
    "src/config.py": (
        "from dataclasses import dataclass\n\n\n@dataclass\nclass Config:\n"
        "    name: str = 'demo'\n\n\ndef load(path: str) -> Config:\n    return Config(name=path)\n"
    ),
    "src/utils.py": (
        "from datetime import datetime\n\n\ndef now() -> int:\n    return datetime.now().year\n"
    ),
    "README.md": "# Demo workspace\n\nA small project for the page audit.\n",
}

PRICES = [
    {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "prompt_price": 3.0, "completion_price": 15.0},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini", "prompt_price": 0.15, "completion_price": 0.6},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "prompt_price": 0.3, "completion_price": 2.5},
]


def seed(ctx) -> None:  # noqa: ANN001
    root = ctx.paths.projects_dir / "audit-demo"
    for name, text in PROJECT_FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    conversation = ctx.conversations.create("Sandbox policy review", select=False)
    ctx.conversations.add_message(conversation.id, "user", "Draft a safe sandbox policy for generated C code.")
    ctx.conversations.add_message(
        conversation.id,
        "assistant",
        "Jail the working directory, cap the wall clock at ten seconds and never install packages.",
        model_id="openai/gpt-4o-mini",
        input_tokens=4200,
        output_tokens=900,
    )
    ctx.prompts.create("Refactor safely", "Explain the change you are about to make before editing.", category="code")
    ctx.memory.add("The user prefers short, verifiable answers.")
    ctx.outputs.create(name="sandbox-policy.md", content="# Sandbox policy\n\nTen-second wall clock.\n")
    ctx.tasks.record(kind="code", title="Review the sandbox policy", status="ok", detail="two files")
    ctx.settings.update({"ai.openrouter_cache": PRICES, "usage.monthly_budget": 4.0})

    ledger = ctx.conversations.create("Usage ledger", select=False)
    today = datetime.utcnow()
    for offset in range(0, 30, 3):
        message = ctx.conversations.add_message(
            ledger.id,
            "assistant",
            "ledger entry",
            model_id="anthropic/claude-sonnet-4",
            input_tokens=24_000 + offset * 900,
            output_tokens=3800 + offset * 120,
        )
        when = today - timedelta(days=offset, hours=offset % 7)
        with ctx.db.session() as session:
            session.execute(
                update(Message).where(Message.id == message.id).values(created_at=when, updated_at=when)
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "ui"))
    parser.add_argument("--lang", default="en")
    parser.add_argument("--theme", default="midnight")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    home = Path(tempfile.mkdtemp(prefix="myai-audit-"))
    ctx = build_context(home, log=False)
    ctx.boot()
    seed(ctx)

    app = QApplication(sys.argv[:1])
    theme = ThemeManager(app, ctx.settings, ctx.paths)
    runtime.set_manager(theme)
    theme.apply()
    ctx.settings.update({"ui.language": args.lang, "ui.theme": args.theme})
    window = MainWindow(ctx, theme)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    project = window.code_page.projects.open_folder(ctx.paths.projects_dir / "audit-demo")
    window.code_page.set_project(project)
    window.code_page.open_file("src/engine.py")
    app.processEvents()

    written: list[str] = []
    for route in sorted(AI_ROUTES):
        window._navigate(route)
        app.processEvents()
        window.toasts.clear()
        app.processEvents()
        widget = window._pages[route]
        widget.repaint()
        app.processEvents()
        pixmap = QPixmap(window.size())
        pixmap.fill(0)
        window.render(pixmap)
        path = out / f"audit_{route}_{args.theme}_{args.lang}.png"
        pixmap.save(str(path))
        written.append(str(path))
        print(f"[audit] {route}", flush=True)

    window.close()
    print("\n".join(written))
    ctx.shutdown()
    if not args.keep:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
