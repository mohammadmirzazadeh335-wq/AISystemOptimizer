"""The Connectivity card on the API page: proxy choice, save and probe."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from myai.i18n import tr
from myai.services.net import NetworkProbe


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def test_the_card_shows_the_proxy_actually_in_use(ui, monkeypatch) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    page = window.api_page
    ctx.settings.update({"network.proxy_mode": "off"})
    page.refresh()
    assert page.proxy_state.text() == tr("api.proxy_direct")

    ctx.settings.update({"network.proxy_mode": "manual", "network.proxy_url": "127.0.0.1:10809"})
    page.refresh()
    assert page.proxy_mode.value == "manual"
    assert "127.0.0.1:10809" in page.proxy_state.text()


def test_saving_a_manual_proxy_persists_and_normalises(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    page = window.api_page
    page.proxy_mode.set_value("manual")
    page._on_proxy_mode("manual")  # noqa: SLF001
    assert page.proxy_url.isEnabled()
    page.proxy_url.setText("127.0.0.1:10809")
    page._save_proxy()  # noqa: SLF001
    pump()
    assert ctx.settings.get("network.proxy_mode") == "manual"
    assert ctx.settings.get("network.proxy_url") == "http://127.0.0.1:10809"
    assert "127.0.0.1:10809" in page.proxy_state.text()


def test_a_broken_proxy_is_refused_before_it_is_saved(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    page = window.api_page
    page.proxy_mode.set_value("manual")
    page._on_proxy_mode("manual")  # noqa: SLF001
    page.proxy_url.setText("not a proxy")
    messages: list[tuple[str, str]] = []
    page.notify.connect(lambda text, tone: messages.append((text, tone)))
    page._save_proxy()  # noqa: SLF001
    pump()
    assert ctx.settings.get("network.proxy_url") == ""
    assert messages and messages[-1][1] == "error"


def test_leaving_manual_mode_disables_the_address(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    page = window.api_page
    page.proxy_mode.set_value("system")
    page._on_proxy_mode("system")  # noqa: SLF001
    assert page.proxy_url.isEnabled() is False


def test_the_probe_reports_the_failing_stage(ui, monkeypatch) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    page = window.api_page
    monkeypatch.setattr(
        page,
        "client",
        lambda: type(
            "Fake",
            (),
            {
                "diagnose": staticmethod(
                    lambda: NetworkProbe(
                        ok=False,
                        stage="tls",
                        detail="SSLZeroReturnError: closed",
                        elapsed_ms=42,
                    )
                )
            },
        )(),
    )
    page._probe_network()  # noqa: SLF001
    pump()
    for _ in range(50):
        pump()
    assert tr("api.stage_tls") in page.proxy_state.text()
    assert "SSLZeroReturnError" in page.proxy_state.text()


def test_the_probe_receives_a_proxy_result(ui, monkeypatch) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    page = window.api_page
    monkeypatch.setattr(
        page,
        "client",
        lambda: type(
            "Fake",
            (),
            {
                "diagnose": staticmethod(
                    lambda: NetworkProbe(
                        ok=True, stage="http", detail="HTTP 200 · TLSv1.3", elapsed_ms=310
                    )
                )
            },
        )(),
    )
    page._probe_network()  # noqa: SLF001
    for _ in range(50):
        pump()
    assert "310" in page.proxy_state.text()
    assert page.proxy_state.property("role") == "success"


def test_error_text_is_translated_not_raw_english(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    page = window.api_page
    from myai.services.openrouter import TimeoutProviderError

    error = TimeoutProviderError(
        "The provider did not answer in time",
        message_key="error.api_timeout",
        details="ReadTimeout · proxy=direct",
    )
    text = page._localized_error(error)  # noqa: SLF001
    assert "The provider did not answer" not in text
    assert tr("error.api_timeout") in text
    assert "ReadTimeout" in text
