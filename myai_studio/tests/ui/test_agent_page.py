"""Agent Mode inside the real window.

The provider is scripted (no network here); every tool call runs the real
handler against a temporary project, and the page is asserted to render what
actually happened — including denials, failures and the step limit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from myai.i18n import set_language, tr
from myai.services.openrouter import ChatResult, StreamStats, ToolCall
from myai.services.tools import registry
from myai.ui.views.agent_page import ApprovalRequest
from myai.ui.widgets.dialogs import ConfirmDialog
from myai.ui.widgets.foundation import ElidedLabel


def pump(ms: int = 30) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)


def answer(text: str) -> ChatResult:
    return ChatResult(text=text, stats=StreamStats(total_tokens=11, completion_tokens=4))


def call(name: str, arguments: dict | str = "{}", *, call_id: str = "c1",
         text: str = "") -> ChatResult:
    payload = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ChatResult(
        text=text,
        stats=StreamStats(finish_reason="tool_calls", total_tokens=7),
        tool_calls=[ToolCall(id=call_id, name=name, arguments=payload)],
    )


class FakeClient:
    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[dict] = []

    def stream_chat(self, **kwargs):  # noqa: ANN201
        self.requests.append(kwargs)
        item = self.script.pop(0) if self.script else answer("done")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(kwargs)
        return item


def labels(page) -> list[str]:  # noqa: ANN001
    texts = [label.text() for label in page.findChildren(QLabel) if label.text()]
    texts += [label.text() for label in page.findChildren(ElidedLabel) if label.text()]
    return texts


@pytest.fixture()
def agent_env(ui, tmp_path: Path):  # noqa: ANN001
    window, ctx, _theme = ui
    from myai.services.openrouter import model_to_dict, parse_model

    project = tmp_path / "agent-demo"
    (project / "src").mkdir(parents=True)
    (project / "app.py").write_text("print('hello from agent page')\n", encoding="utf-8")
    (project / "src" / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
    (project / "notes.md").write_text("# notes\n", encoding="utf-8")

    ctx.secrets.set_api_key("sk-or-v1-test-agent-key")
    models = [
        parse_model({"id": "test/tool-model", "name": "Tool Model",
                     "supported_parameters": ["tools", "temperature"]}),
        parse_model({"id": "test/plain-model", "name": "Plain Model",
                     "supported_parameters": ["temperature"]}),
    ]
    ctx.settings.update({
        "ai.openrouter_cache": [model_to_dict(model) for model in models],
        "ai.default_model": "test/tool-model",
        "code.last_project": str(project),
        "code.recent_projects": [{"path": str(project), "name": project.name}],
    })
    window._navigate("agent")
    pump()
    page = window.agent_page

    def install(script: list) -> FakeClient:
        client = FakeClient(script)
        ctx.chat._client_factory = lambda: client  # noqa: SLF001 - the provider seam
        return client

    def run(task: str, *, confirm=None, timeout: float = 15.0):  # noqa: ANN001, ANN202
        page.task_edit.setPlainText(task)
        page._update_controls()
        if confirm is not None:
            page._confirm = confirm
        page.start()
        deadline = time.monotonic() + timeout
        while page._thread is not None and time.monotonic() < deadline:
            pump(20)
        pump(60)
        return page._run

    def wait(timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while page._thread is not None and time.monotonic() < deadline:
            pump(20)
        pump(60)

    yield window, ctx, page, project, install, run, wait

    page.shutdown()


# --------------------------------------------------------------------- basics
def test_agent_route_shows_the_real_page(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("agent")
    pump()
    assert window.stack.currentWidget() is window.agent_page
    assert window._current_route == "agent"


def test_tools_card_lists_every_tool_with_a_risk(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    total = len(page.registry.specs())
    assert page.tools_box.count() == total + 1  # one row per tool plus the stretch
    assert str(total) in page.tools_count.text()
    text = "\n".join(labels(page))
    assert tr("agent.tool_read_file") in text
    assert tr("agent.tool_run_file") in text
    assert tr("agent.risk_execute") in text



def test_unavailable_tools_state_their_reason(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    text = "\n".join(labels(page))
    assert tr("agent.reason_network_off") in text
    assert tr("agent.reason_no_image") in text
    assert tr("agent.reason_no_project") not in text  # the project is open


def test_enabling_network_names_the_next_missing_thing(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, _install, _run, _wait = agent_env
    page.network_toggle.setChecked(True)
    pump()
    assert ctx.settings.get("agent.allow_network") is True
    assert tr("agent.reason_no_endpoint") in "\n".join(labels(page))
    ctx.settings.update({"web.search_url": "https://searx.example/s"})
    page.refresh_tools()
    text = "\n".join(labels(page))
    assert tr("agent.reason_no_endpoint") not in text
    assert tr("agent.reason_no_token") in text


def test_only_tool_capable_models_are_offered(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    assert page.model_select.value == "test/tool-model"
    assert page.model_badge.text() == tr("agent.model_tools_yes")


def test_a_non_tool_default_falls_back_to_a_tool_model(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, _install, _run, _wait = agent_env
    ctx.settings.update({"ai.default_model": "test/plain-model"})
    page.refresh()
    pump()
    assert page.model_select.value == "test/tool-model"
    assert ctx.settings.get("ai.default_model") == "test/tool-model"


def test_without_a_key_the_run_button_is_disabled(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, _install, _run, _wait = agent_env
    ctx.secrets.delete_all()
    page.refresh()
    page.task_edit.setPlainText("Read app.py")
    page._update_controls()
    assert page.run_button.isEnabled() is False
    assert page.run_hint.text() == tr("agent.need_key")


def test_project_is_picked_up_from_code_studio(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, project, _install, _run, _wait = agent_env
    assert page.project is not None
    assert page.project.root == project.resolve()
    assert page.project_badge.text() == "agent-demo"


# ------------------------------------------------------------------- running
def test_run_executes_a_real_tool_and_renders_the_steps(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, run, _wait = agent_env
    client = install([call("read_file", {"path": "app.py"}), answer("The app prints a greeting.")])
    result = run("Read app.py and summarise it")

    assert result is not None and result.status == "ok"
    assert result.final_text == "The app prints a greeting."
    assert len(client.requests) == 2
    assert client.requests[0]["tools"], "tool schemas must be sent to the model"
    text = "\n".join(labels(page))
    assert "hello from agent page" in text
    assert "The app prints a greeting." in text
    assert tr("agent.tool_read_file") in text
    assert page.status_badge.text() == tr("agent.status_ok")


def test_write_tool_waits_for_approval_then_writes(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, project, install, run, _wait = agent_env
    asked: list[tuple[str, dict]] = []

    def confirm(tool, arguments):  # noqa: ANN001
        asked.append((tool.id, dict(arguments)))
        return True

    install([call("write_file", {"path": "new.txt", "content": "approved"}), answer("written")])
    result = run("Create new.txt", confirm=confirm)
    assert result is not None and result.status == "ok"
    assert asked == [("write_file", {"path": "new.txt", "content": "approved"})]
    assert (project / "new.txt").read_text(encoding="utf-8") == "approved"


def test_declined_write_is_never_applied(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, project, install, run, _wait = agent_env
    install([call("write_file", {"path": "denied.txt", "content": "x"}), answer("ok")])
    result = run("Create denied.txt", confirm=lambda tool, args: False)
    assert not (project / "denied.txt").exists()
    assert result is not None
    assert result.steps[0].kind == "denied"
    assert tr("agent.tool_state_denied") in "\n".join(labels(page))


def test_approval_dialog_is_shown_and_a_rejection_blocks_the_write(
    agent_env, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _window, _ctx, page, project, install, _run, wait = agent_env
    seen: list[str] = []

    def fake_exec(dialog):  # noqa: ANN001
        seen.append(dialog.title_label.text())
        return ConfirmDialog.DialogCode.Rejected

    monkeypatch.setattr(ConfirmDialog, "exec", fake_exec)
    install([call("write_file", {"path": "dialog.txt", "content": "x"}), answer("fine")])
    page.task_edit.setPlainText("Write dialog.txt")
    page._update_controls()
    page.start()
    wait()
    assert seen == [tr("agent.approve_title")]
    assert not (project / "dialog.txt").exists()
    assert any(step.kind == "denied" for step in page._run.steps)


def test_cancel_stops_a_running_agent(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, _run, wait = agent_env

    def slow(kwargs):  # noqa: ANN001
        cancel = kwargs["cancel"]
        for _ in range(500):
            if cancel.is_set():
                return ChatResult(text="stopped", cancelled=True)
            time.sleep(0.01)
        return answer("never")

    install([slow])
    page.task_edit.setPlainText("Do something slow")
    page._update_controls()
    page.start()
    pump(80)
    assert page._thread is not None and page._thread.is_alive()
    page.stop()
    wait()
    assert page._run is not None and page._run.status == "cancelled"
    assert page.status_badge.text() == tr("agent.status_cancelled")


def test_step_limit_is_reported(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, install, run, _wait = agent_env
    ctx.settings.update({"agent.max_steps": 2})
    install([call("list_files"), call("list_files")])
    result = run("Loop forever")
    assert result is not None and result.status == "limit"
    assert page.status_badge.text() == tr("agent.status_limit")


def test_unknown_tool_failure_is_visible(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, run, _wait = agent_env
    install([call("format_disk"), answer("I cannot.")])
    result = run("Format the disk")
    assert result is not None and result.status == "ok"
    text = "\n".join(labels(page))
    assert "Unknown tool" in text
    assert tr("agent.tool_state_failed") in text


def test_provider_failure_marks_the_run_failed(agent_env) -> None:  # noqa: ANN001
    from myai.core.errors import RateLimitError

    _window, _ctx, page, _project, install, run, _wait = agent_env
    install([RateLimitError("Too many requests", message_key="error.rate_limit")])
    result = run("Do it")
    assert result is not None and result.status == "error"
    assert page.status_badge.text() == tr("agent.status_error")
    assert "Too many requests" in "\n".join(labels(page))


def test_history_rows_restore_an_earlier_run(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, run, _wait = agent_env
    install([call("list_files"), answer("first answer")])
    first = run("First task")
    pump(40)
    assert page.runs_box.count() >= 1
    assert page.runs_empty.isVisible() is False
    page._show_run(first)
    pump(30)
    assert "first answer" in "\n".join(labels(page))


def test_empty_timeline_is_hidden_after_the_first_step(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, run, _wait = agent_env
    assert page.empty_state.isVisible() is True
    install([answer("hello")])
    run("Say hello")
    assert page.empty_state.isVisible() is False


def test_an_empty_task_shows_a_warning_and_does_not_start(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    notices: list[tuple[str, str]] = []
    page.notify.connect(lambda message, tone: notices.append((message, tone)))
    page.start()
    assert page._thread is None
    assert notices and notices[-1][0] == tr("agent.need_task")


def test_task_survives_a_theme_rebuild(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    page.task_edit.setPlainText("A task that must survive a rebuild")
    page.rebuild()
    pump(30)
    assert page.task_edit.toPlainText() == "A task that must survive a rebuild"


# ---------------------------------------------------------------------- i18n
def test_persian_switches_the_agent_page_to_rtl(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, _install, _run, _wait = agent_env
    ctx.settings.update({"ui.language": "fa"})
    pump(60)
    assert QApplication.layoutDirection() == QApplication.layoutDirection().RightToLeft
    assert page.lead.text().startswith("هدف")
    assert page.run_button.text() == "اجرای عامل"
    assert page.tools_count.text().endswith("آماده")


def test_english_is_ltr_again(agent_env) -> None:  # noqa: ANN001
    _window, ctx, page, _project, _install, _run, _wait = agent_env
    set_language("fa")
    ctx.settings.update({"ui.language": "en"})
    pump(60)
    assert QApplication.layoutDirection() == QApplication.layoutDirection().LeftToRight
    assert page.run_button.text() == "Run agent"


# ------------------------------------------------------------------ shutdown
def test_shutdown_denies_a_pending_approval(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    tool = registry().get("write_file")
    assert tool is not None
    request = ApprovalRequest(tool=tool, arguments={"path": "x", "content": "y"})
    page._pending = request
    page.shutdown()
    assert request.approved is False


def test_confirm_denies_immediately_when_closing(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    tool = registry().get("write_file")
    assert tool is not None
    page._closing = True
    assert page._confirm(tool, {"path": "x", "content": "y"}) is False


def test_stop_denies_a_waiting_confirmation(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, _install, _run, _wait = agent_env
    tool = registry().get("write_file")
    assert tool is not None
    request = ApprovalRequest(tool=tool, arguments={"path": "x", "content": "y"})
    page._pending = request
    page.stop()
    assert request.approved is False
    assert request.event.is_set() is True


def test_shutdown_stops_a_running_thread(agent_env) -> None:  # noqa: ANN001
    _window, _ctx, page, _project, install, _run, _wait = agent_env

    def slow(kwargs):  # noqa: ANN001
        cancel = kwargs["cancel"]
        for _ in range(300):
            if cancel.is_set():
                return ChatResult(text="stopped", cancelled=True)
            time.sleep(0.01)
        return answer("never")

    install([slow])
    page.task_edit.setPlainText("Long task")
    page._update_controls()
    page.start()
    pump(60)
    page.shutdown()
    assert page._thread is None or not page._thread.is_alive()


# ------------------------------------------------------------------- settings
@pytest.fixture()
def settings_dialog(ui):  # noqa: ANN001
    from myai.services.backup import BackupService
    from myai.ui.views.settings_dialog import SettingsDialog

    window, ctx, theme = ui
    dialog = SettingsDialog(
        window,
        ctx.settings,
        theme,
        ctx.paths,
        ctx.db,
        ctx.secrets,
        BackupService(ctx.paths, ctx.db, ctx.settings),
        initial="agent",
    )
    dialog.show()
    pump()
    yield dialog, ctx
    dialog.reject()
    dialog.deleteLater()
    pump(10)


def test_agent_settings_page_is_real(settings_dialog) -> None:  # noqa: ANN001
    dialog, _ctx = settings_dialog
    assert dialog.agent_search_input is not None
    assert dialog.agent_token_input.echoMode().name == "Password"
    # The page must no longer be the phase-locked placeholder.
    assert "Phase 4" not in "\n".join(labels(dialog))


def test_agent_settings_toggles_persist(settings_dialog) -> None:  # noqa: ANN001
    from myai.ui.widgets.buttons import ToggleSwitch

    dialog, ctx = settings_dialog
    assert len(dialog.findChildren(ToggleSwitch)) >= 2
    dialog._set_agent_network(True)
    assert ctx.settings.get("agent.allow_network") is True
    dialog._set_agent_network(False)
    assert ctx.settings.get("agent.allow_network") is False


def test_github_token_is_stored_encrypted_and_removable(settings_dialog) -> None:  # noqa: ANN001
    dialog, ctx = settings_dialog
    dialog.agent_token_input.setText("ghp_settings_token")
    dialog._save_github_token()
    assert ctx.secrets.get("github_token") == "ghp_settings_token"
    assert "ghp_settings_token" not in dialog.agent_token_state.text()
    assert tr("settings.agent_token_stored") in dialog.agent_token_state.text()
    dialog._clear_github_token()
    assert ctx.secrets.has("github_token") is False
    assert tr("settings.agent_token_missing") in dialog.agent_token_state.text()


def test_empty_token_is_rejected(settings_dialog) -> None:  # noqa: ANN001
    dialog, ctx = settings_dialog
    dialog.agent_token_input.setText("   ")
    dialog._save_github_token()
    assert ctx.secrets.has("github_token") is False


def test_search_endpoint_is_validated(settings_dialog) -> None:  # noqa: ANN001
    dialog, ctx = settings_dialog
    dialog._write("web.search_url", "ftp://not-http")
    assert ctx.settings.get("web.search_url") == ""
    dialog._write("web.search_url", "https://searx.example/search")
    assert ctx.settings.get("web.search_url") == "https://searx.example/search"


def test_small_window_stacks_the_workspace_without_overlap(agent_env) -> None:  # noqa: ANN001
    """A 1120x720 window must scroll, not squash: panes stack, rows keep height."""
    from PySide6.QtCore import Qt

    from myai.ui.theme import runtime

    window, ctx, page, _project, _install, _run, _wait = agent_env
    ctx.settings.update({"ui.font_scale": 1.0, "ui.language": "en"})
    window.resize(1120, 720)
    pump(80)
    window._navigate("agent")
    pump(80)

    assert page.splitter.orientation() == Qt.Orientation.Vertical
    # While stacked the panes keep real heights and the workspace scrolls.
    bar = page.workspace_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    assert page.splitter.height() >= bar.maximum()
    # Tool rows never collapse below their readable height.
    assert all(row.height() >= runtime.px(40) for row in page._tool_rows.values())

    window.resize(1600, 1000)
    pump(80)
    assert page.splitter.orientation() == Qt.Orientation.Horizontal


def test_short_window_keeps_the_sidebar_empty_state_readable(agent_env) -> None:  # noqa: ANN001
    from myai.ui.theme import runtime

    window, ctx, _page, _project, _install, _run, _wait = agent_env
    ctx.settings.update({"ui.font_scale": 1.0})
    window.sidebar.refresh()
    for size in ((1440, 900), (1120, 720)):
        window.resize(*size)
        pump(80)
        window.sidebar._fit_chat_list()
        pump(60)
        stack = window.sidebar._stack
        empty = window.sidebar.empty_state
        # It used to collapse to 31 px and paint the hint over the LIBRARY
        # rows; the list now keeps a readable strip and the column scrolls.
        assert stack.height() >= runtime.px(76)
        assert empty.height() >= runtime.px(70)
        assert empty.body_label.height() > 6
        # Every navigation row keeps its full height and stays reachable through
        # the column's own scrollbar (it is a 900 px column with 16 rows).
        for key, button in window.sidebar.nav_buttons.items():
            assert button.height() >= runtime.px(24), key
        assert window.sidebar.nav_scroll.verticalScrollBar().maximum() >= 0
        assert window.sidebar._stack.geometry().bottom() < window.sidebar.nav_buttons["agent"].geometry().top()
