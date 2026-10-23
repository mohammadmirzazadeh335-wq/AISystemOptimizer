"""Network reachability: proxy discovery, timeouts and the staged probe.

The failure these tests exist for: a machine behind a VPN keeps the proxy in
the operating system settings, not in environment variables, so an HTTP client
that only reads the environment times out while the browser works.
"""

from __future__ import annotations

import http.server
import socket
import socketserver
import threading

import pytest

from myai.core.errors import ConfigurationError, ValidationError
from myai.services.net import (
    NetworkOptions,
    client_kwargs,
    mask_proxy,
    normalize_proxy,
    options_from_settings,
    probe,
    resolve_proxy,
    system_proxy,
)
from myai.services.openrouter import OpenRouterClient


# ------------------------------------------------------------------- addresses
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("127.0.0.1:10809", "http://127.0.0.1:10809"),
        ("  http://127.0.0.1:7890  ", "http://127.0.0.1:7890"),
        ("https://proxy.local:8443", "https://proxy.local:8443"),
        ("socks5://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("http://user:pass@10.0.0.2:3128", "http://user:pass@10.0.0.2:3128"),
        ("", ""),
    ],
)
def test_proxy_addresses_are_normalised(raw: str, expected: str) -> None:
    assert normalize_proxy(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["http://nohost", "ftp://10.0.0.1:21", "http://10.0.0.1:99999", "http://10.0.0.1:abc"],
)
def test_nonsense_proxies_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_proxy(raw)


def test_credentials_are_masked() -> None:
    assert mask_proxy("http://user:secret@10.0.0.2:3128") == "http://***@10.0.0.2:3128"
    assert "secret" not in mask_proxy("http://user:secret@10.0.0.2:3128")
    assert mask_proxy("http://127.0.0.1:10809") == "http://127.0.0.1:10809"


# -------------------------------------------------------------------- discovery
def test_environment_proxy_is_found() -> None:
    url, source = system_proxy({"HTTPS_PROXY": "http://127.0.0.1:2080"})
    assert url == "http://127.0.0.1:2080"
    assert source == "env:HTTPS_PROXY"


def test_garbage_environment_proxy_is_skipped() -> None:
    url, source = system_proxy(
        {"HTTPS_PROXY": "not a proxy", "HTTP_PROXY": "http://127.0.0.1:8888"}
    )
    assert url == "http://127.0.0.1:8888"
    assert source == "env:HTTP_PROXY"


def test_no_proxy_anywhere_is_a_direct_connection() -> None:
    assert system_proxy({}) == ("", "")


def test_modes_decide_what_is_used() -> None:
    environ = {"HTTPS_PROXY": "http://127.0.0.1:2080"}
    assert resolve_proxy(NetworkOptions(mode="off"), environ).url == ""
    assert resolve_proxy(NetworkOptions(mode="manual", manual_proxy="127.0.0.1:10809"), environ).url == (
        "http://127.0.0.1:10809"
    )
    assert resolve_proxy(NetworkOptions(mode="system"), environ).url == "http://127.0.0.1:2080"


def test_client_kwargs_carry_the_proxy_and_the_timeouts() -> None:
    options = NetworkOptions(mode="manual", manual_proxy="127.0.0.1:10809", connect_timeout=9.0, read_timeout=45.0)
    kwargs = client_kwargs(options)
    assert kwargs["proxy"] == "http://127.0.0.1:10809"
    assert kwargs["timeout"].connect == 9.0
    assert kwargs["timeout"].read == 45.0
    assert "proxy" not in client_kwargs(NetworkOptions(mode="off"))


def test_settings_round_trip_into_options(ctx) -> None:  # noqa: ANN001
    ctx.settings.update(
        {"network.proxy_mode": "manual", "network.proxy_url": "127.0.0.1:10809", "network.connect_timeout": 25.0}
    )
    options = options_from_settings(ctx.settings)
    assert options.mode == "manual"
    assert options.manual_proxy == "http://127.0.0.1:10809"
    assert options.connect_timeout == 25.0


def test_settings_reject_a_broken_proxy(ctx) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        ctx.settings.set("network.proxy_url", "ftp://host:21")
    with pytest.raises(ValidationError):
        ctx.settings.set("network.proxy_mode", "sometimes")
    with pytest.raises(ValidationError):
        ctx.settings.set("network.connect_timeout", 0.5)


# ---------------------------------------------------------------------- probe
class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        body = b'{"data": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:  # noqa: ANN002 - stdlib API
        pass


@pytest.fixture()
def local_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_probe_reaches_a_real_local_endpoint(local_server: str) -> None:
    result = probe(local_server, NetworkOptions(mode="off"))
    assert result.ok is True
    assert result.stage in {"tcp", "http"}
    assert result.proxy == ""


def test_probe_names_a_dead_proxy_as_the_failure(local_server: str) -> None:  # noqa: ARG001
    # Port 1 on loopback refuses immediately — no real network involved.
    options = NetworkOptions(mode="manual", manual_proxy="127.0.0.1:1", connect_timeout=3.0)
    result = probe("https://openrouter.ai/api/v1", options)
    assert result.ok is False
    assert result.stage == "proxy"
    assert "refused" in result.detail.lower() or "error" in result.detail.lower()


def test_probe_never_resolves_the_target_when_a_proxy_is_set(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []

    def fake_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(str(host))
        return original(host, *args, **kwargs)

    original = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    options = NetworkOptions(mode="manual", manual_proxy="127.0.0.1:1", connect_timeout=3.0)
    result = probe("https://openrouter.ai/api/v1", options)
    # Resolving the proxy is fine; resolving the provider is the proxy's job.
    assert "openrouter.ai" not in calls
    assert result.stage == "proxy"


# --------------------------------------------------------------------- client
def test_client_uses_the_configured_proxy(ctx) -> None:  # noqa: ANN001
    ctx.settings.update({"network.proxy_mode": "manual", "network.proxy_url": "127.0.0.1:10809"})
    client = OpenRouterClient(
        lambda: "sk-or-v1-" + "a" * 24,
        network=options_from_settings(ctx.settings),
    )
    assert client.proxy_label() == "http://127.0.0.1:10809"
    with client._client() as http:  # noqa: SLF001 - the transport is the point
        assert http._transport is not None  # noqa: SLF001


def test_a_broken_proxy_is_a_configuration_error_not_a_traceback(ctx) -> None:  # noqa: ANN001
    client = OpenRouterClient(
        lambda: "sk-or-v1-" + "a" * 24,
        network=NetworkOptions(mode="manual", manual_proxy="127.0.0.1:10809"),
    )
    # A SOCKS address without the optional dependency must be explained, not
    # raise an ImportError from three layers down.
    client.network = NetworkOptions(mode="manual", manual_proxy="socks5://127.0.0.1:1080")
    with pytest.raises(ConfigurationError) as caught:
        client._client()  # noqa: SLF001
    assert "socks" in str(caught.value).lower()
