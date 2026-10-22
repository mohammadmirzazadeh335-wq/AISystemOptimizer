"""Web research (Phase 5).

This build has **no search provider**, and the page says so. What is real is
*direct page reading*: paste a URL and the app fetches it, extracts the title and
the readable text, and lets the user copy or save the result. That is a genuine
HTTP request — not a simulated search — and it is labelled as such in the UI.

A commercial search API can be plugged in later by giving this service a
``search_provider``; until then ``search_available`` stays ``False``.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from ..core.errors import ValidationError

logger = logging.getLogger(__name__)

USER_AGENT = "MyAIStudio/0.5 (desktop; +https://openrouter.ai)"
MAX_BYTES = 2_000_000
MAX_TEXT = 200_000
TIMEOUT = 20.0
SKIP_TAGS = {
    "script", "style", "noscript", "svg", "template", "head", "iframe", "canvas",
    "nav", "footer", "form", "button", "select", "option",
}
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "main", "br", "hr", "li", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "ul", "ol",
}


@dataclass(frozen=True)
class WebPage:
    url: str
    final_url: str
    status: int
    content_type: str
    title: str
    text: str
    bytes_received: int
    elapsed_ms: int

    @property
    def words(self) -> int:
        return len(self.text.split())


class _Extractor(HTMLParser):
    """Small, dependency-free readability pass: title + block text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag, attrs) -> None:  # noqa: ANN001
        if tag.lower() in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        raw = unescape("".join(self._chunks))
        lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in raw.splitlines()]
        kept: list[str] = []
        for line in lines:
            if not line:
                if kept and kept[-1] != "":
                    kept.append("")
                continue
            kept.append(line)
        return "\n".join(kept).strip()


def _is_private_host(host: str) -> bool:
    name = host.strip("[]").lower()
    if name in {"localhost", "localhost.localdomain"} or name.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(name).is_private or ipaddress.ip_address(name).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(name, None)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
    return False


def validate_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        raise ValidationError("Enter a URL", message_key="web.error_empty")
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("Only http and https URLs can be read", message_key="web.error_scheme")
    if not parsed.hostname:
        raise ValidationError("That URL has no host", message_key="web.error_host")
    if _is_private_host(parsed.hostname):
        raise ValidationError("Local network addresses are blocked", message_key="web.error_private")
    return text


class WebService:
    """Reads a single public page. Search is not implemented by design."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout: float = TIMEOUT) -> None:
        self._transport = transport
        self._timeout = timeout
        self._search_provider = None

    # ------------------------------------------------------------------ state
    @property
    def search_available(self) -> bool:
        return self._search_provider is not None

    @property
    def reading_available(self) -> bool:
        return True

    # ------------------------------------------------------------------- fetch
    def fetch(self, url: str) -> WebPage:
        target = validate_url(url)
        started = time.perf_counter()
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"},
            ) as client:
                with client.stream("GET", target) as response:
                    chunks: list[bytes] = []
                    received = 0
                    for chunk in response.iter_bytes():
                        chunks.append(chunk)
                        received += len(chunk)
                        if received >= MAX_BYTES:
                            break
                    body = b"".join(chunks)
                    status = response.status_code
                    final_url = str(response.url)
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        except httpx.HTTPError as exc:
            logger.warning("web_fetch_failed url=%s error=%s", target, type(exc).__name__)
            raise ValidationError(
                f"The page could not be read ({type(exc).__name__}).",
                message_key="web.error_network",
                details=str(exc)[:300],
            ) from exc

        if status >= 400:
            raise ValidationError(
                f"The server answered {status}.",
                message_key="web.error_status",
                details=str(status),
            )

        encoding = "utf-8"
        title = ""
        if content_type in {"text/html", "application/xhtml+xml"} or (
            not content_type and b"<html" in body[:2048].lower()
        ):
            parser = _Extractor()
            try:
                parser.feed(body.decode(encoding, errors="replace"))
            except Exception:  # noqa: BLE001 - malformed markup must not fail the fetch
                logger.debug("web_extract_failed", exc_info=True)
            text = parser.text()
            title = " ".join(parser.title.split())
        else:
            text = body.decode(encoding, errors="replace")
        text = text[:MAX_TEXT]
        return WebPage(
            url=target,
            final_url=final_url,
            status=status,
            content_type=content_type or "unknown",
            title=title,
            text=text,
            bytes_received=received,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
