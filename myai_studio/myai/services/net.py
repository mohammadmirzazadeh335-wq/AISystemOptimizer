"""How the app reaches the internet: proxy, timeouts and a staged probe.

Windows ships no environment variables for its proxy, and a VPN client in
"system proxy" mode writes the WinINET registry keys instead.  A Python app
that only reads ``HTTPS_PROXY`` therefore fails with a connect timeout on a
machine that can browse the web fine — the exact symptom the API page reports
as "the provider did not answer in time".  This module reads every source the
operating system offers, so the app behaves like the browser next to it.

Nothing here stores or logs credentials: proxy URLs are masked before they are
shown or written to the log.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import httpx

from ..core.platform import creation_flags

PROXY_MODES = ("system", "manual", "off")
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h", "socks4", "socks4a")
ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


@dataclass(frozen=True)
class NetworkOptions:
    """What the HTTP client needs to know about this machine's network."""

    mode: str = "system"
    manual_proxy: str = ""
    connect_timeout: float = 20.0
    read_timeout: float = 120.0

    @property
    def trust_env(self) -> bool:
        """Env vars are read only in system mode, where they are one source."""
        return self.mode == "system"


def mask_proxy(url: str) -> str:
    """``http://user:secret@host:8080`` → ``http://***@host:8080``."""
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://***@{host}{port}"


def normalize_proxy(value: str | None) -> str:
    """Return a usable proxy URL, ``""`` for "none", or raise ``ValueError``.

    Users type ``127.0.0.1:10809`` far more often than a full URL, so a missing
    scheme means HTTP.  A bare host without a port is rejected: silently
    defaulting to 80 produces a proxy nobody is listening on.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme not in PROXY_SCHEMES:
        raise ValueError(f"unsupported proxy scheme: {scheme or '(none)'}")
    if not parts.hostname:
        raise ValueError("proxy host is missing")
    try:
        port = parts.port
    except ValueError as exc:  # non-numeric port
        raise ValueError("proxy port is not a number") from exc
    if port is None:
        raise ValueError("proxy port is missing")
    if not 1 <= port <= 65535:
        raise ValueError("proxy port is out of range")
    auth = ""
    if parts.username is not None:
        password = f":{parts.password}" if parts.password is not None else ""
        auth = f"{parts.username}{password}@"
    path = parts.path if parts.path not in ("", "/") else ""
    return f"{scheme}://{auth}{parts.hostname}:{port}{path}"


def _from_windows_registry() -> str:
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except Exception:  # pragma: no cover - not on Windows
        return ""
    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not int(enabled):
                return ""
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return ""
    server = str(server or "").strip()
    if not server:
        return ""
    # "http=host:port;https=host:port" — prefer the HTTPS entry, then HTTP.
    if "=" in server:
        mapping = {}
        for chunk in server.split(";"):
            name, _, value = chunk.partition("=")
            if value:
                mapping[name.strip().lower()] = value.strip()
        server = mapping.get("https") or mapping.get("http") or ""
        if not server:
            return ""
    if "://" not in server:
        server = f"http://{server}"
    return server


def _from_macos_scutil() -> str:
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=creation_flags(),
        ).stdout
    except Exception:  # pragma: no cover - macOS only
        return ""
    values: dict[str, str] = {}
    for line in out.splitlines():
        match = re.match(r"\s*([A-Za-z]+)\s*:\s*(\S+)", line)
        if match:
            values[match.group(1)] = match.group(2)
    for scheme in ("HTTPS", "HTTP"):
        if values.get(f"{scheme}Enable") == "1" and values.get(f"{scheme}Proxy"):
            port = values.get(f"{scheme}Port", "")
            host = values[f"{scheme}Proxy"]
            return f"http://{host}:{port}" if port else f"http://{host}"
    return ""


def system_proxy(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Best proxy this machine offers, plus where it came from."""
    env = os.environ if environ is None else environ
    for key in ENV_KEYS:
        value = (env.get(key) or "").strip()
        if value:
            try:
                return normalize_proxy(value), f"env:{key}"
            except ValueError:
                continue
    registry = _from_windows_registry()
    if registry:
        try:
            return normalize_proxy(registry), "windows-registry"
        except ValueError:
            pass
    macos = _from_macos_scutil()
    if macos:
        try:
            return normalize_proxy(macos), "macos-scutil"
        except ValueError:
            pass
    return "", ""


def options_from_settings(settings) -> NetworkOptions:  # noqa: ANN001 - avoid a cycle
    return NetworkOptions(
        mode=str(settings.get("network.proxy_mode", "system") or "system"),
        manual_proxy=str(settings.get("network.proxy_url", "") or ""),
        connect_timeout=float(settings.get("network.connect_timeout", 20.0) or 20.0),
        read_timeout=float(settings.get("network.read_timeout", 120.0) or 120.0),
    )


@dataclass(frozen=True)
class ProxyChoice:
    url: str
    source: str

    @property
    def label(self) -> str:
        if not self.url:
            return "direct"
        return f"{mask_proxy(self.url)} ({self.source})"


def resolve_proxy(options: NetworkOptions, environ: dict[str, str] | None = None) -> ProxyChoice:
    """Decide the proxy for this call.  Raises ``ValueError`` on bad input."""
    mode = options.mode if options.mode in PROXY_MODES else "system"
    if mode == "off":
        return ProxyChoice("", "disabled")
    if mode == "manual":
        url = normalize_proxy(options.manual_proxy)
        return ProxyChoice(url, "manual" if url else "manual-empty")
    url, source = system_proxy(environ)
    return ProxyChoice(url, source or "none")


def client_kwargs(options: NetworkOptions, environ: dict[str, str] | None = None) -> dict:
    """Keyword arguments for ``httpx.Client`` that honour this network."""
    choice = resolve_proxy(options, environ)
    kwargs: dict = {
        "timeout": options_timeout(options),
        "trust_env": False,
    }
    if choice.url:
        if choice.url.startswith("socks") and not _socks_available():
            raise RuntimeError(
                "SOCKS proxy needs the optional socksio package; "
                "use an HTTP proxy port instead"
            )
        kwargs["proxy"] = choice.url
    return kwargs


def options_timeout(options: NetworkOptions):
    connect = max(3.0, float(options.connect_timeout or 20.0))
    read = max(connect, float(options.read_timeout or 120.0))
    return httpx.Timeout(read, connect=connect, write=read, pool=connect)


def _socks_available() -> bool:
    try:
        import socksio  # noqa: F401,PLC0415
    except Exception:
        return False
    return True


# --------------------------------------------------------------------- probe
@dataclass(frozen=True)
class NetworkProbe:
    """One staged connection attempt, from DNS to a real HTTP response."""

    ok: bool
    stage: str
    detail: str
    elapsed_ms: int
    proxy: str = ""
    status: int | None = None

    def with_detail(self, text: str) -> NetworkProbe:
        return replace(self, detail=text)


def _stage_result(stage: str, detail: str, started: float, proxy: str) -> NetworkProbe:
    return NetworkProbe(
        ok=False,
        stage=stage,
        detail=detail,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        proxy=proxy,
    )


def _tcp_reachable(host: str, port: int, timeout: float) -> str:
    """``""`` when a socket opened, otherwise the reason it did not."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ""
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def _open_tunnel(raw: socket.socket, host: str, port: int, timeout: float) -> str:
    """Issue an HTTP CONNECT through an already-connected proxy socket."""
    host_header = f"{host}:{port}"
    raw.settimeout(timeout)
    raw.sendall(
        f"CONNECT {host_header} HTTP/1.1\r\nHost: {host_header}\r\n\r\n".encode("ascii")
    )
    head = raw.recv(512).split(b"\r\n", 1)[0].decode("latin-1", "replace")
    if " 200 " not in head:
        return f"CONNECT rejected: {head or '(no response)'}"
    return ""


def probe(base_url: str, options: NetworkOptions, *, environ=None) -> NetworkProbe:  # noqa: ANN001
    """Walk proxy/DNS → TCP → TLS → HTTP and stop at the first failure.

    Every stage is separate on purpose: "timeout" alone does not tell a user
    whether DNS, the proxy, the firewall or the provider is at fault.  With a
    proxy configured the target's DNS record is deliberately not resolved
    locally — the proxy does that, and doing it twice would report a false DNS
    failure on machines where only the proxy can resolve the name.
    """
    started = time.perf_counter()
    try:
        choice = resolve_proxy(options, environ)
    except ValueError as exc:
        return _stage_result("proxy-config", str(exc), started, "")
    proxy = mask_proxy(choice.url)
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    timeout = max(3.0, float(options.connect_timeout or 20.0))
    if not host:
        return _stage_result("config", "the endpoint has no host", started, proxy)

    socket_test = None
    if choice.url:
        proxied = urlsplit(choice.url)
        problem = _tcp_reachable(
            proxied.hostname or "",
            proxied.port or (443 if proxied.scheme == "https" else 1080),
            timeout,
        )
        if problem:
            return _stage_result("proxy", problem, started, proxy)
    else:
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            return _stage_result("dns", f"{type(exc).__name__}: {exc}", started, proxy)
        if not infos:
            return _stage_result("dns", "no address returned", started, proxy)
        address = infos[0][4]
        problem = _tcp_reachable(address[0], address[1], timeout)
        if problem:
            return _stage_result("tcp", problem, started, proxy)
        socket_test = address

    if not secure:
        return NetworkProbe(
            True, "tcp", "connected (plain HTTP)", int((time.perf_counter() - started) * 1000), proxy
        )

    protocol = "TLS"
    try:
        if choice.url:
            proxied = urlsplit(choice.url)
            raw = socket.create_connection(
                (proxied.hostname or "", proxied.port or 1080), timeout=timeout
            )
        else:
            raw = socket.create_connection(socket_test or (host, port), timeout=timeout)
        with raw:
            if choice.url:
                problem = _open_tunnel(raw, host, port, timeout)
                if problem:
                    return _stage_result("proxy", problem, started, proxy)
            context = ssl.create_default_context()
            with context.wrap_socket(raw, server_hostname=host) as tls:
                protocol = tls.version() or "TLS"
    except ssl.SSLCertVerificationError as exc:
        return _stage_result("tls", f"certificate: {exc.verify_message}", started, proxy)
    except ssl.SSLError as exc:
        return _stage_result("tls", f"{type(exc).__name__}: {exc.reason or exc}", started, proxy)
    except OSError as exc:
        return _stage_result("tcp", f"{type(exc).__name__}: {exc}", started, proxy)

    try:
        kwargs = client_kwargs(options, environ)
        with httpx.Client(base_url=base_url.rstrip("/"), follow_redirects=True, **kwargs) as http:
            response = http.get("/models")
            status = response.status_code
    except httpx.HTTPError as exc:
        return _stage_result("http", f"{type(exc).__name__}: {exc}", started, proxy)
    except RuntimeError as exc:
        return _stage_result("proxy-config", str(exc), started, proxy)
    return NetworkProbe(
        ok=True,
        stage="http",
        detail=f"HTTP {status} · {protocol}",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        proxy=proxy,
        status=status,
    )
