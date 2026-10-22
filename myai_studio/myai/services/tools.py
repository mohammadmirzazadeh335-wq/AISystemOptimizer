"""Validated, permission-aware tools for Agent Mode.

A tool is only usable when it is registered here with a JSON schema, a risk level
and a real handler. Anything the machine cannot do — a web endpoint that is not
configured, a GitHub token that is absent, image generation without a provider —
is reported as unavailable with the exact reason instead of being simulated.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..core.errors import AppError, NotFoundError, SandboxError, ToolError, ValidationError
from .memory import MemoryService
from .outputs import OutputService
from .patches import apply_unified
from .projects import MAX_TREE_ENTRIES, Project, ProjectService
from .runner import Runner
from .settings import SettingsService
from .toolchains import ToolchainUnavailable

logger = logging.getLogger(__name__)

READ = "read"
WRITE = "write"
EXECUTE = "execute"
NETWORK = "network"
RISKS = (READ, WRITE, EXECUTE, NETWORK)
#: Risks that need an explicit user confirmation before execution.
SENSITIVE = {WRITE, EXECUTE, NETWORK}

MAX_TOOL_OUTPUT = 20_000
MAX_READ_CHARS = 120_000


#: Why a tool cannot run, in the language used by prompts and logs. The UI
#: translates the same keys, so a Persian user never sees a raw English reason.
REASON_TEXT = {
    "agent.reason_no_settings": "Settings are not available.",
    "agent.reason_no_project": "No project folder is open. Open one in Code Studio first.",
    "agent.reason_network_off": "Network access is disabled (Settings → Agent → Allow network tools).",
    "agent.reason_no_endpoint": "No search endpoint is configured (web.search_url).",
    "agent.reason_no_token": "No GitHub token is stored (Settings → Agent → GitHub token).",
    "agent.reason_no_web": "No page reader is available in this build.",
    "agent.reason_no_image": (
        "No image provider is configured. OpenRouter text models cannot create images, "
        "so this tool is unavailable rather than simulated."
    ),
}


class ToolUnavailable(ToolError):
    """The tool exists but cannot run on this machine / configuration."""

    code = "tool.unavailable"


class ToolDenied(SandboxError):
    """The user refused the call or no confirmation channel was available."""

    code = "tool.denied"


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "data": self.data}


@dataclass(frozen=True)
class ToolSpec:
    id: str
    description: str
    parameters: dict[str, Any]
    risk: str
    handler: Callable[["ToolContext", dict[str, Any]], ToolResult]
    label_key: str = ""
    requires_project: bool = False
    availability: Callable[["ToolContext"], tuple[str, dict[str, Any]] | None] | None = None

    def reason_key(self, ctx: "ToolContext") -> tuple[str, dict[str, Any]] | None:
        """Why this tool cannot run (translatable key + params), or ``None``."""
        if self.requires_project and ctx.project is None:
            return "agent.reason_no_project", {}
        if self.availability is not None:
            return self.availability(ctx)
        return None

    def reason(self, ctx: "ToolContext") -> str | None:
        """English reason for prompts, logs and tests."""
        found = self.reason_key(ctx)
        if found is None:
            return None
        key, params = found
        template = REASON_TEXT.get(key, key)
        return template.format(**params) if params else template


@dataclass
class ToolContext:
    projects: ProjectService | None = None
    project: Project | None = None
    runner: Runner | None = None
    memory: MemoryService | None = None
    outputs: OutputService | None = None
    settings: SettingsService | None = None
    secrets: Any = None  # SecretStore; typed loosely to keep the module import-light
    conversation_id: str | None = None
    cancel: threading.Event | None = None
    #: ``myai.services.web.WebService``; only ``fetch()`` is used here.
    web: Any = None
    http_transport: httpx.BaseTransport | None = None
    timeout_seconds: float = 20.0

    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()


# ------------------------------------------------------------------ validation
_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
    """Validate against the small JSON-schema subset this app writes."""
    if not isinstance(arguments, dict):
        raise ValidationError(
            f"{spec.id}: arguments must be an object", message_key="agent.bad_arguments"
        )
    schema = spec.parameters or {}
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        if name not in arguments or arguments[name] in (None, ""):
            raise ValidationError(
                f"{spec.id}: missing required argument '{name}'",
                message_key="agent.missing_argument",
                context={"tool": spec.id, "argument": name},
            )
    for name, value in arguments.items():
        rule = properties.get(name)
        if rule is None:
            raise ValidationError(
                f"{spec.id}: unknown argument '{name}'",
                message_key="agent.unknown_argument",
                context={"tool": spec.id, "argument": name},
            )
        expected = rule.get("type")
        if expected in _TYPES and not isinstance(value, _TYPES[expected]):
            raise ValidationError(
                f"{spec.id}: '{name}' must be {expected}",
                message_key="agent.bad_argument_type",
                context={"tool": spec.id, "argument": name},
            )
        if expected == "integer" and isinstance(value, bool):
            raise ValidationError(
                f"{spec.id}: '{name}' must be an integer",
                message_key="agent.bad_argument_type",
            )
        if expected in ("integer", "number") and isinstance(value, int | float):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValidationError(
                    f"{spec.id}: '{name}' must be >= {rule['minimum']}",
                    message_key="agent.argument_range",
                    context={"tool": spec.id, "argument": name},
                )
            if "maximum" in rule and value > rule["maximum"]:
                raise ValidationError(
                    f"{spec.id}: '{name}' must be <= {rule['maximum']}",
                    message_key="agent.argument_range",
                    context={"tool": spec.id, "argument": name},
                )
        if expected == "string":
            if "enum" in rule and value not in rule["enum"]:
                raise ValidationError(
                    f"{spec.id}: '{name}' must be one of {rule['enum']}",
                    message_key="agent.argument_enum",
                    context={"tool": spec.id, "argument": name},
                )
            maximum = rule.get("maxLength")
            if maximum and len(str(value)) > maximum:
                raise ValidationError(
                    f"{spec.id}: '{name}' is longer than {maximum} characters",
                    message_key="agent.argument_range",
                )


# ------------------------------------------------------------------ the tools
def _need_project(ctx: ToolContext) -> Project:
    if ctx.project is None or ctx.projects is None:
        raise ToolUnavailable("No project folder is open.")
    return ctx.project


def _tool_list_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    folder = str(args.get("path") or "").strip().replace("\\", "/").strip("/")
    entries = ctx.projects.tree(project, limit=600)  # type: ignore[union-attr]
    direct: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        relative = entry.relative
        if folder:
            if relative == folder:
                continue
            if not relative.startswith(folder + "/"):
                continue
            rest = relative[len(folder) + 1 :]
        else:
            rest = relative
        if not rest:
            continue
        first = rest.split("/", 1)[0]
        if first in seen:
            continue
        seen.add(first)
        is_dir = "/" in rest or entry.is_dir
        if is_dir:
            direct.append(f"{first}/")
        else:
            direct.append(f"{first}  ({entry.size} bytes)")
    direct.sort(key=str.lower)
    if not direct:
        return ToolResult(True, f"No files in {folder or 'the project root'}.", {"count": 0})
    body = "\n".join(direct[:200])
    if len(direct) > 200:
        body += f"\n… {len(direct) - 200} more entries"
    return ToolResult(True, body, {"count": len(direct), "folder": folder})


def _tool_read_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    content = ctx.projects.read(project, relative)  # type: ignore[union-attr]
    if content.binary:
        raise ToolError(
            f"{relative} is a binary file and cannot be read as text.",
            message_key="agent.binary_file",
        )
    text = content.text
    truncated = False
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS]
        truncated = True
    note = f"\n… truncated at {MAX_READ_CHARS} characters" if truncated else ""
    return ToolResult(
        True,
        f"# {relative} ({content.size} bytes, {content.language})\n{text}{note}",
        {"path": relative, "bytes": content.size, "language": content.language,
         "truncated": truncated or content.truncated},
    )


def _tool_write_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    text = str(args["content"])
    content = ctx.projects.write(project, relative, text)  # type: ignore[union-attr]
    return ToolResult(
        True,
        f"Wrote {content.size} bytes to {relative}.",
        {"path": relative, "bytes": content.size},
    )


def _tool_delete_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    ctx.projects.delete(project, relative)  # type: ignore[union-attr]
    return ToolResult(True, f"Deleted {relative}.", {"path": relative})


def _tool_search_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    query = str(args["query"]).strip()
    pattern = str(args.get("glob") or "").strip()
    limit = int(args.get("max_results") or 50)
    matches = ctx.projects.search(  # type: ignore[union-attr]
        project, query, pattern=pattern, limit=max(1, min(limit, 200))
    )
    if not matches:
        where = f" in {pattern}" if pattern else ""
        return ToolResult(True, f"No files{where} contain “{query}”.", {"count": 0})
    lines = [f"{item['path']}:{item['line']}: {item['text']}" for item in matches]
    body = "\n".join(lines)[:MAX_TOOL_OUTPUT]
    return ToolResult(True, body, {"count": len(matches), "query": query, "glob": pattern})


def _tool_make_folder(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip().replace("\\", "/").strip("/")
    target = ctx.projects.make_folder(project, relative)  # type: ignore[union-attr]
    return ToolResult(
        True,
        f"Created folder {relative or '.'} ({target}).",
        {"path": relative, "absolute": str(target)},
    )


def _tool_create_project(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.projects is None:
        raise ToolUnavailable("No project service is available.")
    project = ctx.projects.create_project(str(args["name"]))
    return ToolResult(
        True,
        f"Created project “{project.name}” at {project.path}. "
        "Open it in Code Studio (or ask to write files here after opening it).",
        {"name": project.name, "path": project.path},
    )


def _tool_run_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    if ctx.runner is None:
        raise ToolUnavailable("No runner is available.")
    source = project.root / relative
    if not source.is_file():
        raise NotFoundError(f"{relative} does not exist.")
    configured = float(ctx.settings.get("code.timeout_seconds", 10.0)) if ctx.settings else 10.0
    requested = args.get("timeout_seconds")
    timeout = min(float(requested), 60.0) if isinstance(requested, int | float) else configured
    try:
        plan = ctx.runner.plan_for(source, cwd=project.root, timeout_seconds=timeout)
    except ToolchainUnavailable as exc:
        raise ToolUnavailable(exc.detail) from exc
    result = ctx.runner.run(plan, cancel_event=ctx.cancel)
    lines = [f"$ {step.argv[0]} {' '.join(step.argv[1:])}" for step in plan.steps]
    if result.stdout:
        lines.append(result.stdout.rstrip())
    if result.stderr:
        lines.append("stderr:\n" + result.stderr.rstrip())
    lines.append(f"[{result.status}] exit={result.exit_code} in {result.duration_ms} ms")
    output = "\n".join(lines)[:MAX_TOOL_OUTPUT]
    return ToolResult(
        result.status == "ok",
        output,
        {"status": result.status, "exit_code": result.exit_code, "duration_ms": result.duration_ms},
    )


def _tool_remember(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.memory is None:
        raise ToolUnavailable("Memory is not available.")
    scope = str(args.get("scope") or "global")
    if scope == "conversation" and not ctx.conversation_id:
        scope = "global"
    entry = ctx.memory.add(
        str(args["text"]),
        scope=scope,
        conversation_id=ctx.conversation_id if scope == "conversation" else None,
        source="agent",
    )
    return ToolResult(True, f"Remembered ({entry.scope}): {entry.content}", {"id": entry.id})


def _tool_recall(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.memory is None:
        raise ToolUnavailable("Memory is not available.")
    query = str(args["query"]).strip().lower()
    limit = int(args.get("limit") or 5)
    tokens = [token for token in re.split(r"\s+", query) if token]
    entries = ctx.memory.all_for_conversation(ctx.conversation_id)
    matches = []
    for entry in entries:
        haystack = entry.content.lower()
        if all(token in haystack for token in tokens):
            matches.append(entry)
    if not matches:
        return ToolResult(True, f"No memory entry matches '{query}'.", {"count": 0})
    body = "\n".join(f"- [{entry.scope}] {entry.content}" for entry in matches[:limit])
    return ToolResult(True, body, {"count": len(matches)})


def _tool_save_output(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.outputs is None:
        raise ToolUnavailable("Output Studio is not available.")
    entry = ctx.outputs.create(
        str(args["name"]),
        str(args["content"]),
        conversation_id=ctx.conversation_id,
    )
    return ToolResult(
        True,
        f"Saved '{entry.name}' to Output Studio ({entry.size_bytes} bytes).",
        {"id": entry.id, "name": entry.name},
    )


def _network_reason(ctx: ToolContext) -> tuple[str, dict[str, Any]] | None:
    if ctx.settings is None:
        return "agent.reason_no_settings", {}
    if not bool(ctx.settings.get("agent.allow_network", False)):
        return "agent.reason_network_off", {}
    return None


def _tool_web_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    reason = _network_reason(ctx)
    if reason:
        raise ToolUnavailable(REASON_TEXT.get(reason[0], reason[0]))
    url = str(ctx.settings.get("web.search_url", "") or "").strip()  # type: ignore[union-attr]
    if not url:
        raise ToolUnavailable(REASON_TEXT["agent.reason_no_endpoint"])
    query = str(args["query"]).strip()
    headers = {"Accept": "application/json"}
    if ctx.secrets is not None:
        token = ctx.secrets.get("web_api_key")
        if token:
            headers["X-API-Key"] = token
    try:
        with httpx.Client(
            transport=ctx.http_transport, timeout=ctimeout(ctx)
        ) as client:
            response = client.get(
                url,
                params={
                    "q": query,
                    "format": "json",
                    "safesearch": int(bool(ctx.settings.get("web.safe_search", True))),  # type: ignore[union-attr]
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ToolError(
            f"Search endpoint answered HTTP {exc.response.status_code}.",
            message_key="agent.web_failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Could not reach the search endpoint: {type(exc).__name__}.",
            message_key="agent.web_failed",
        ) from exc
    except ValueError as exc:
        raise ToolError("Search endpoint did not return JSON.", message_key="agent.web_failed") from exc
    rows = payload.get("results") if isinstance(payload, dict) else None
    results = []
    for row in (rows or [])[:8]:
        if not isinstance(row, dict):
            continue
        results.append(
            {
                "title": str(row.get("title") or "").strip(),
                "url": str(row.get("url") or "").strip(),
                "snippet": str(row.get("content") or "").strip()[:300],
            }
        )
    if not results:
        return ToolResult(True, f"No results for '{query}'.", {"count": 0})
    body = "\n".join(
        f"{index}. {item['title']}\n   {item['url']}\n   {item['snippet']}"
        for index, item in enumerate(results, start=1)
    )
    return ToolResult(True, body, {"count": len(results)})


def ctimeout(ctx: ToolContext) -> float:
    return float(ctx.timeout_seconds or 20.0)


_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _github_reason(ctx: ToolContext) -> tuple[str, dict[str, Any]] | None:
    reason = _network_reason(ctx)
    if reason:
        return reason
    token = ctx.secrets.get("github_token") if ctx.secrets is not None else None
    if not token:
        return "agent.reason_no_token", {}
    return None


def _github(ctx: ToolContext, method: str, path: str, payload: dict | None = None) -> dict:
    token = ctx.secrets.get("github_token") if ctx.secrets is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MyAI-Studio",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(transport=ctx.http_transport, timeout=ctimeout(ctx)) as client:
            response = client.request(
                method, f"https://api.github.com{path}", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ToolError(
            f"GitHub answered HTTP {status}.",
            message_key="agent.github_failed",
            details=f"HTTP {status}",
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Could not reach GitHub: {type(exc).__name__}.",
            message_key="agent.github_failed",
        ) from exc


def _tool_github_issues(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    repo = str(args["repo"]).strip()
    if not _REPO.match(repo):
        raise ValidationError("repo must look like 'owner/name'")
    state = str(args.get("state") or "open")
    rows = _github(ctx, "GET", f"/repos/{repo}/issues?state={state}&per_page=20")
    issues = [row for row in rows if isinstance(row, dict) and "pull_request" not in row]
    if not issues:
        return ToolResult(True, f"No {state} issues in {repo}.", {"count": 0})
    body = "\n".join(
        f"#{row.get('number')} [{row.get('state')}] {row.get('title')} "
        f"— {(row.get('user') or {}).get('login', '?')}"
        for row in issues
    )
    return ToolResult(True, body, {"count": len(issues)})


def _tool_github_comment(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    repo = str(args["repo"]).strip()
    if not _REPO.match(repo):
        raise ValidationError("repo must look like 'owner/name'")
    number = int(args["issue"])
    payload = _github(ctx, "POST", f"/repos/{repo}/issues/{number}/comments", {"body": str(args["body"])})
    return ToolResult(
        True,
        f"Commented on {repo}#{number}: {payload.get('html_url', '')}".strip(),
        {"url": payload.get("html_url", "")},
    )


def _image_reason(ctx: ToolContext) -> tuple[str, dict[str, Any]] | None:  # noqa: ARG001
    return "agent.reason_no_image", {}


def _tool_generate_image(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:  # noqa: ARG001
    raise ToolUnavailable(REASON_TEXT["agent.reason_no_image"])




# ---------------------------------------------------------- new agent tools
_TEXT_SKIP = {"", "binary"}


def _text_files(ctx: ToolContext, project: Project, *, limit: int = 600) -> list:
    """Text files in tree order, skipping obvious binaries."""
    rows = []
    for entry in ctx.projects.tree(project, limit=MAX_TREE_ENTRIES):  # type: ignore[union-attr]
        if entry.is_dir or not entry.language or entry.language in _TEXT_SKIP:
            continue
        rows.append(entry)
        if len(rows) >= limit:
            break
    return rows


def _tool_project_map(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:  # noqa: ARG001
    project = _need_project(ctx)
    entries = ctx.projects.tree(project)  # type: ignore[union-attr]
    files = [entry for entry in entries if not entry.is_dir]
    folders = [entry for entry in entries if entry.is_dir]
    total_bytes = sum(entry.size for entry in files)

    by_language: dict[str, list[int]] = {}
    for entry in files:
        language = entry.language or "other"
        bucket = by_language.setdefault(language, [0, 0])
        bucket[0] += 1
        bucket[1] += entry.size

    # Real line counts, bounded: a project with a 50 MB log file must not stall
    # the agent thread.
    lines_by_language: dict[str, int] = {}
    counted = 0
    for entry in _text_files(ctx, project, limit=300):
        if entry.size > 400_000:
            continue
        try:
            content = ctx.projects.read(project, entry.relative)  # type: ignore[union-attr]
        except (ToolError, OSError, ValidationError):
            continue
        lines_by_language[entry.language] = lines_by_language.get(entry.language, 0) + len(
            content.text.splitlines()
        )
        counted += 1

    order = sorted(by_language.items(), key=lambda item: (-item[1][0], item[0]))
    language_rows = []
    for language, (count, size) in order[:12]:
        lines = lines_by_language.get(language)
        suffix = f", {lines:,} lines" if lines is not None else ""
        language_rows.append(f"- {language}: {count} files, {format_bytes(size)}{suffix}")

    largest = sorted(files, key=lambda entry: entry.size, reverse=True)[:5]
    largest_rows = [f"- {entry.relative} ({format_bytes(entry.size)})" for entry in largest]

    known_entry_points = {
        "main.py", "__main__.py", "app.py", "cli.py", "manage.py", "server.py",
        "index.js", "server.js", "main.ts", "package.json", "pyproject.toml",
        "requirements.txt", "README.md",
    }
    entry_points = [entry.relative for entry in files if entry.name in known_entry_points][:12]

    body = [
        f"# {project.name}",
        f"{len(files)} files in {len(folders)} folders, {format_bytes(total_bytes)}"
        f" (line counts from {counted} text files).",
        "",
        "## Languages",
        *(language_rows or ["- (no text files)"]),
        "",
        "## Largest files",
        *(largest_rows or ["- (empty project)"]),
        "",
        "## Entry points / manifests",
        *([f"- {path}" for path in entry_points] or ["- none of the usual names were found"]),
    ]
    return ToolResult(
        True,
        "\n".join(body)[:MAX_TOOL_OUTPUT],
        {
            "files": len(files),
            "folders": len(folders),
            "bytes": total_bytes,
            "languages": {key: value[0] for key, value in by_language.items()},
        },
    )


def _clean_pattern(raw: str) -> str:
    pattern = (raw or "").strip().replace("\\", "/")
    if not pattern:
        raise ValidationError("A file pattern is required.", message_key="agent.missing_argument")
    if pattern.startswith("/") or re.match(r"^[A-Za-z]:/", pattern):
        raise ValidationError("Absolute patterns are not allowed.", message_key="error.absolute_path")
    if ".." in pattern.split("/"):
        raise ValidationError("Patterns cannot leave the project.", message_key="error.path_traversal")
    return pattern


def _tool_find_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    pattern = _clean_pattern(str(args["pattern"]))
    limit = max(1, min(int(args.get("limit") or 40), 200))
    matched: list[tuple[str, int, float]] = []
    for entry in ctx.projects.tree(project):  # type: ignore[union-attr]
        if entry.is_dir:
            continue
        relative = entry.relative
        if not (fnmatch.fnmatch(relative.lower(), pattern.lower())
                or fnmatch.fnmatch(entry.name.lower(), pattern.lower())):
            continue
        try:
            modified = os.stat(ctx.projects.resolve(project, relative)).st_mtime  # type: ignore[union-attr]
        except OSError:
            modified = 0.0
        matched.append((relative, entry.size, modified))
    if not matched:
        return ToolResult(True, f"No files match {pattern}.", {"count": 0, "pattern": pattern})
    matched.sort(key=lambda row: (-row[2], row[0].lower()))
    shown = matched[:limit]
    body = "\n".join(
        f"{path}  ({format_bytes(size)})" for path, size, _modified in shown
    )
    if len(matched) > len(shown):
        body += f"\n… {len(matched) - len(shown)} more"
    return ToolResult(
        True,
        body[:MAX_TOOL_OUTPUT],
        {"count": len(matched), "pattern": pattern, "shown": len(shown)},
    )


def _tool_read_lines(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    start = max(1, int(args.get("start") or 1))
    end = int(args.get("end") or 0)
    content = ctx.projects.read(project, relative)  # type: ignore[union-attr]
    if content.binary:
        raise ToolError(
            f"{relative} is a binary file and cannot be read as text.",
            message_key="agent.binary_file",
        )
    lines = content.text.splitlines()
    total = len(lines)
    if end <= 0 or end < start:
        end = min(total, start + 119)  # 120 lines by default
    end = min(end, total, start + 399)
    if start > total:
        return ToolResult(
            True,
            f"{relative} has {total} lines; line {start} does not exist.",
            {"path": relative, "lines": total, "start": start, "end": end},
        )
    width = len(str(end))
    body = "\n".join(
        f"{number:>{width}} | {lines[number - 1]}" for number in range(start, end + 1)
    )
    return ToolResult(
        True,
        f"# {relative} lines {start}-{end} of {total}\n{body}"[:MAX_TOOL_OUTPUT],
        {"path": relative, "total_lines": total, "start": start, "end": end},
    )


_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b[\s:,-]*(.*)")


def _tool_scan_todos(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    limit = max(1, min(int(args.get("limit") or 60), 200))
    found: list[tuple[str, int, str, str]] = []
    counts: dict[str, int] = {}
    for entry in _text_files(ctx, project, limit=500):
        if entry.size > 512_000:
            continue
        try:
            text = ctx.projects.read(project, entry.relative).text  # type: ignore[union-attr]
        except (ToolError, OSError, ValidationError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = _TODO_RE.search(line)
            if match is None:
                continue
            tag = match.group(1)
            counts[tag] = counts.get(tag, 0) + 1
            if len(found) < limit:
                note = match.group(2).strip()[:160]
                found.append((entry.relative, number, tag, note))
    if not found:
        return ToolResult(True, "No TODO/FIXME/HACK/XXX/BUG markers were found.", {"count": 0})
    summary = ", ".join(f"{tag} {count}" for tag, count in sorted(counts.items()))
    body = "\n".join(f"{path}:{line}: {tag} {note}".strip() for path, line, tag, note in found)
    return ToolResult(
        True,
        f"{sum(counts.values())} markers ({summary})\n{body}"[:MAX_TOOL_OUTPUT],
        {"count": sum(counts.values()), "by_tag": counts},
    )


def _tool_diff_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    left = str(args["path_a"]).strip()
    right = str(args["path_b"]).strip()
    first = ctx.projects.read(project, left)  # type: ignore[union-attr]
    second = ctx.projects.read(project, right)  # type: ignore[union-attr]
    if first.binary or second.binary:
        raise ToolError(
            "One of the files is binary; a text diff is not meaningful.",
            message_key="agent.binary_file",
        )
    diff = list(
        difflib.unified_diff(
            first.text.splitlines(),
            second.text.splitlines(),
            fromfile=left,
            tofile=right,
            lineterm="",
        )
    )
    if not diff:
        return ToolResult(True, f"{left} and {right} are identical.", {"identical": True})
    body = "\n".join(diff)
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return ToolResult(
        True,
        body[:MAX_TOOL_OUTPUT],
        {"identical": False, "added": added, "removed": removed, "truncated": len(body) > MAX_TOOL_OUTPUT},
    )


def _tool_apply_patch(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    project = _need_project(ctx)
    relative = str(args["path"]).strip()
    patch = str(args["patch"])
    current = ctx.projects.read(project, relative)  # type: ignore[union-attr]
    if current.binary:
        raise ToolError(
            f"{relative} is a binary file.", message_key="agent.binary_file"
        )
    # A failed patch raises before anything is written: the file is untouched.
    updated, applied = apply_unified(current.text, patch)
    written = ctx.projects.write(project, relative, updated)  # type: ignore[union-attr]
    return ToolResult(
        True,
        f"Applied {applied} hunk(s) to {relative}; the file is now {written.size} bytes.",
        {"path": relative, "hunks": applied, "bytes": written.size},
    )


def _web_reason(ctx: ToolContext) -> tuple[str, dict[str, Any]] | None:
    reason = _network_reason(ctx)
    if reason:
        return reason
    if ctx.web is None:
        return "agent.reason_no_web", {}
    return None


def _tool_fetch_url(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    reason = _web_reason(ctx)
    if reason:
        raise ToolUnavailable(REASON_TEXT.get(reason[0], reason[0]))
    url = str(args["url"]).strip()
    try:
        page = ctx.web.fetch(url)
    except AppError:
        # A rejected URL or an HTTP status error already carries a translated
        # message; do not flatten it into a generic tool failure.
        raise
    except Exception as exc:  # noqa: BLE001 - sockets raise many types
        raise ToolError(
            f"Could not read {url}: {type(exc).__name__}.",
            message_key="agent.web_failed",
            details=type(exc).__name__,
        ) from exc
    text = page.text[:MAX_TOOL_OUTPUT]
    header = (
        f"# {page.title}\n{page.final_url} · HTTP {page.status} · "
        f"{format_bytes(page.bytes_received)} · {page.elapsed_ms} ms"
    )
    note = "\n… truncated for the model" if len(page.text) > len(text) else ""
    return ToolResult(
        True,
        f"{header}\n\n{text}{note}",
        {
            "url": page.final_url,
            "status": page.status,
            "chars": len(page.text),
            "truncated": len(page.text) > len(text),
        },
    )


def format_bytes(size: int) -> str:
    """Compact, locale-independent size for tool output."""
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def default_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="list_files",
            label_key="agent.tool_list_files",
            description=(
                "List files and folders in the open project. Use it before reading a file "
                "whose name you are unsure about."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 400,
                             "description": "Sub-folder relative to the project root."}
                },
            },
            risk=READ,
            handler=_tool_list_files,
            requires_project=True,
        ),
        ToolSpec(
            id="read_file",
            label_key="agent.tool_read_file",
            description="Read one text file from the open project, verbatim.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "maxLength": 400}},
                "required": ["path"],
            },
            risk=READ,
            handler=_tool_read_file,
            requires_project=True,
        ),
        ToolSpec(
            id="write_file",
            label_key="agent.tool_write_file",
            description=(
                "Create or overwrite a text file inside the open project. The previous "
                "content is replaced; read the file first when you need to keep it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 400},
                    "content": {"type": "string", "maxLength": 300_000},
                },
                "required": ["path", "content"],
            },
            risk=WRITE,
            handler=_tool_write_file,
            requires_project=True,
        ),
        ToolSpec(
            id="search_files",
            label_key="agent.tool_search_files",
            description=(
                "Search the text of every file in the open project (case-insensitive) "
                "and return matching lines with their file and line number."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 200},
                    "glob": {"type": "string", "maxLength": 80,
                             "description": "Optional file filter such as *.py."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["query"],
            },
            risk=READ,
            handler=_tool_search_files,
            requires_project=True,
        ),
        ToolSpec(
            id="make_folder",
            label_key="agent.tool_make_folder",
            description="Create a folder (including parents) inside the open project.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "maxLength": 400}},
                "required": ["path"],
            },
            risk=WRITE,
            handler=_tool_make_folder,
            requires_project=True,
        ),
        ToolSpec(
            id="create_project",
            label_key="agent.tool_create_project",
            description=(
                "Create a new empty project folder under the user's projects directory. "
                "Use it when the user asks for a new project to be started."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "maxLength": 120}},
                "required": ["name"],
            },
            risk=WRITE,
            handler=_tool_create_project,
        ),
        ToolSpec(
            id="delete_file",
            label_key="agent.tool_delete_file",
            description="Delete one file from the open project. This cannot be undone.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "maxLength": 400}},
                "required": ["path"],
            },
            risk=WRITE,
            handler=_tool_delete_file,
            requires_project=True,
        ),
        ToolSpec(
            id="run_file",
            label_key="agent.tool_run_file",
            description=(
                "Run a file with the toolchain installed on this machine and return its "
                "real stdout, stderr and exit code."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 400},
                    "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                },
                "required": ["path"],
            },
            risk=EXECUTE,
            handler=_tool_run_file,
            requires_project=True,
        ),
        ToolSpec(
            id="remember",
            label_key="agent.tool_remember",
            description="Store a durable fact in memory (global by default).",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 2000},
                    "scope": {"type": "string", "enum": ["global", "conversation"]},
                },
                "required": ["text"],
            },
            risk=WRITE,
            handler=_tool_remember,
        ),
        ToolSpec(
            id="recall",
            label_key="agent.tool_recall",
            description="Search the stored memory for facts matching every word of the query.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            risk=READ,
            handler=_tool_recall,
        ),
        ToolSpec(
            id="save_output",
            label_key="agent.tool_save_output",
            description="Save a draft (code, Markdown, JSON…) to Output Studio.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 120},
                    "content": {"type": "string", "maxLength": 300_000},
                },
                "required": ["name", "content"],
            },
            risk=WRITE,
            handler=_tool_save_output,
        ),
        ToolSpec(
            id="web_search",
            label_key="agent.tool_web_search",
            description="Search the web through the configured endpoint; returns titles, URLs and snippets.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "maxLength": 300}},
                "required": ["query"],
            },
            risk=NETWORK,
            handler=_tool_web_search,
            availability=lambda ctx: _network_reason(ctx)
            or (
                None
                if str(ctx.settings.get("web.search_url", "") or "").strip()  # type: ignore[union-attr]
                else ("agent.reason_no_endpoint", {})
            ),
        ),
        ToolSpec(
            id="github_list_issues",
            label_key="agent.tool_github_issues",
            description="List open issues of a GitHub repository.",
            parameters={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "maxLength": 120},
                    "state": {"type": "string", "enum": ["open", "closed", "all"]},
                },
                "required": ["repo"],
            },
            risk=NETWORK,
            handler=_tool_github_issues,
            availability=_github_reason,
        ),
        ToolSpec(
            id="github_comment",
            label_key="agent.tool_github_comment",
            description="Write a comment on a GitHub issue.",
            parameters={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "maxLength": 120},
                    "issue": {"type": "integer", "minimum": 1},
                    "body": {"type": "string", "maxLength": 10_000},
                },
                "required": ["repo", "issue", "body"],
            },
            risk=NETWORK,
            handler=_tool_github_comment,
            availability=_github_reason,
        ),
        ToolSpec(
            id="project_map",
            label_key="agent.tool_project_map",
            description=(
                "Give a structural map of the open project: file and folder counts, languages "
                "with real line counts, the largest files and the usual entry points. Call it "
                "once before exploring so you do not read files blindly."
            ),
            parameters={"type": "object", "properties": {}},
            risk=READ,
            handler=_tool_project_map,
            requires_project=True,
        ),
        ToolSpec(
            id="find_files",
            label_key="agent.tool_find_files",
            description=(
                "Find files by a glob pattern such as **/*.py or *.md, newest first, with sizes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["pattern"],
            },
            risk=READ,
            handler=_tool_find_files,
            requires_project=True,
        ),
        ToolSpec(
            id="read_lines",
            label_key="agent.tool_read_lines",
            description=(
                "Read a numbered line range of one file. Use it for large files instead of "
                "reading everything."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 400},
                    "start": {"type": "integer", "minimum": 1},
                    "end": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
            risk=READ,
            handler=_tool_read_lines,
            requires_project=True,
        ),
        ToolSpec(
            id="scan_todos",
            label_key="agent.tool_scan_todos",
            description=(
                "List TODO / FIXME / HACK / XXX / BUG markers across the project with file, "
                "line and the note next to them."
            ),
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            },
            risk=READ,
            handler=_tool_scan_todos,
            requires_project=True,
        ),
        ToolSpec(
            id="diff_files",
            label_key="agent.tool_diff_files",
            description=(
                "Show the real unified diff between two files of the project (or confirm that "
                "they are identical)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path_a": {"type": "string", "maxLength": 400},
                    "path_b": {"type": "string", "maxLength": 400},
                },
                "required": ["path_a", "path_b"],
            },
            risk=READ,
            handler=_tool_diff_files,
            requires_project=True,
        ),
        ToolSpec(
            id="apply_patch",
            label_key="agent.tool_apply_patch",
            description=(
                "Apply a unified diff (---/+++ and @@ hunks) to one existing file. Context must "
                "match; line numbers may drift. Nothing is written if any hunk fails."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 400},
                    "patch": {"type": "string", "maxLength": 120_000},
                },
                "required": ["path", "patch"],
            },
            risk=WRITE,
            handler=_tool_apply_patch,
            requires_project=True,
        ),
        ToolSpec(
            id="fetch_url",
            label_key="agent.tool_fetch_url",
            description=(
                "Fetch one public http(s) page and return its readable text, title and status. "
                "This is page reading, not a web search."
            ),
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "maxLength": 2000}},
                "required": ["url"],
            },
            risk=NETWORK,
            handler=_tool_fetch_url,
            availability=_web_reason,
        ),
        ToolSpec(
            id="generate_image",
            label_key="agent.tool_generate_image",
            description="Generate an image from a prompt (requires a real image provider).",
            parameters={
                "type": "object",
                "properties": {"prompt": {"type": "string", "maxLength": 1000}},
                "required": ["prompt"],
            },
            risk=NETWORK,
            handler=_tool_generate_image,
            availability=_image_reason,
        ),
    ]


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs if specs is not None else default_specs():
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.risk not in RISKS:
            raise ValueError(f"Unknown risk level: {spec.risk}")
        self._specs[spec.id] = spec

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._specs.get(tool_id)

    def specs(self) -> list[ToolSpec]:
        return [self._specs[key] for key in sorted(self._specs)]

    def available(self, ctx: ToolContext) -> list[ToolSpec]:
        return [spec for spec in self.specs() if spec.reason(ctx) is None]

    def unavailable(self, ctx: ToolContext) -> list[tuple[ToolSpec, str]]:
        rows: list[tuple[ToolSpec, str]] = []
        for spec in self.specs():
            reason = spec.reason(ctx)
            if reason:
                rows.append((spec, reason))
        return rows

    def to_openai(self, ctx: ToolContext) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.id,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self.available(ctx)
        ]

    def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
        *,
        confirm: Callable[[ToolSpec, dict[str, Any]], bool] | None = None,
        require_confirmation: bool = True,
    ) -> ToolResult:
        spec = self.get(tool_id)
        if spec is None:
            raise ToolError(
                f"Unknown tool '{tool_id}'.", message_key="agent.unknown_tool",
                context={"tool": tool_id},
            )
        reason = spec.reason(ctx)
        if reason:
            raise ToolUnavailable(f"{spec.id}: {reason}")
        validate_arguments(spec, arguments)
        if ctx.cancelled():
            raise ToolDenied("Cancelled before the tool started.")
        if spec.risk in SENSITIVE and require_confirmation:
            if confirm is None:
                raise ToolDenied(
                    f"{spec.id} needs confirmation and no confirmation channel is available."
                )
            if not confirm(spec, arguments):
                raise ToolDenied(f"The user declined {spec.id}.")
        started = time.perf_counter()
        result = spec.handler(ctx, arguments)
        logger.info(
            "tool_executed id=%s risk=%s ok=%s ms=%s",
            spec.id, spec.risk, result.ok, int((time.perf_counter() - started) * 1000),
        )
        return result


def registry() -> ToolRegistry:
    """A fresh registry; cheap to build and safe to keep per page."""
    return ToolRegistry()


def describe_for_prompt(tools: ToolRegistry, ctx: ToolContext) -> str:
    """The tool section of the agent's system prompt (model-facing English)."""
    lines = ["Available tools (call them with valid JSON arguments):"]
    for spec in tools.available(ctx):
        required = spec.parameters.get("required") or []
        props = ", ".join(sorted((spec.parameters.get("properties") or {}).keys()))
        lines.append(
            f"- {spec.id}({props}) — {spec.description} "
            f"Risk: {spec.risk}. Required: {', '.join(required) or 'none'}."
        )
    blocked = tools.unavailable(ctx)
    if blocked:
        lines.append("")
        lines.append("Unavailable on this machine (do not pretend to call them):")
        for spec, reason in blocked:
            lines.append(f"- {spec.id}: {reason}")
    return "\n".join(lines)


def tool_result_json(result: ToolResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False)[:MAX_TOOL_OUTPUT]
