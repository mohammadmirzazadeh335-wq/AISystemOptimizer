"""Project atlas: which files import which, laid out for the canvas.

The service reads the open project through :class:`ProjectService` (so every
path guard, size cap and binary check still applies), extracts import
statements for Python and JavaScript/TypeScript, resolves them to files that
actually exist in the project, and computes a deterministic radial layout.

Determinism matters: the canvas must look the same on every open, and the tests
assert coordinates instead of "roughly somewhere". No random numbers, no
``hash()`` (it is salted per process) — positions come from geometry and
``zlib.crc32`` of the path for the small organic jitter.
"""

from __future__ import annotations

import logging
import math
import re
import zlib
from dataclasses import dataclass, field

from ..core.errors import AppError
from .projects import Project, ProjectService

logger = logging.getLogger(__name__)

MAX_FILES = 180
MAX_TEXT_BYTES = 400_000
MAX_EDGES = 900

_PY_FROM = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+([^\n(]*)", re.MULTILINE)
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:import\s+(?:[^'"]+?\s+from\s+)?|export\s+[^'"]*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]""")
_JS_EXTENSIONS = ("", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", "/index.tsx")

#: Language -> palette role. The canvas resolves the role through the theme, so
#: both light and dark themes stay legible.
LANGUAGE_TONE = {
    "python": "info",
    "javascript": "warning",
    "typescript": "accent",
    "c": "violet",
    "cpp": "violet",
    "json": "success",
    "markdown": "text_muted",
    "html": "danger",
    "css": "danger",
    "bash": "success",
    "sql": "info",
    "yaml": "warning",
    "other": "text_faint",
}


@dataclass(frozen=True)
class AtlasNode:
    id: str
    label: str
    language: str
    size: int
    lines: int
    folder: str
    incoming: int
    outgoing: int
    x: float
    y: float
    cluster: int
    tone: str = "text_muted"

    @property
    def degree(self) -> int:
        return self.incoming + self.outgoing


@dataclass(frozen=True)
class AtlasEdge:
    source: str
    target: str
    kind: str = "import"


@dataclass(frozen=True)
class Atlas:
    nodes: tuple[AtlasNode, ...] = ()
    edges: tuple[AtlasEdge, ...] = ()
    stats: dict = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.nodes

    def node(self, node_id: str) -> AtlasNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)


def _strip_comments(text: str, language: str) -> str:
    """Remove comments so a commented-out import is not drawn as an edge."""
    if language == "python":
        return re.sub(r"(?m)^\s*#.*$", "", text)
    text = re.sub(r"(?s)/\*.*?\*/", "", text)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _module_candidates(module: str, source: str) -> list[str]:
    """Likely project paths for a dotted Python module."""
    base = module.replace(".", "/")
    folder = source.rsplit("/", 1)[0] if "/" in source else ""
    candidates = [f"{base}.py", f"{base}/__init__.py"]
    if folder:
        candidates += [f"{folder}/{base}.py", f"{folder}/{base}/__init__.py"]
    return candidates


def _relative_candidates(spec: str, source: str) -> list[str]:
    """Resolve a relative JS specifier (``./util``) against the source file."""
    folder = source.rsplit("/", 1)[0] if "/" in source else ""
    parts = (folder.split("/") if folder else []) + spec.split("/")
    resolved: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
    base = "/".join(resolved)
    return [f"{base}{extension}" for extension in _JS_EXTENSIONS]


def _python_specs(text: str) -> list[str]:
    specs: list[str] = []
    for dots, module, names in _PY_FROM.findall(text):
        if dots:
            if module:
                specs.append("." * len(dots) + module)
            else:
                # ``from . import utils`` imports sibling modules, not names.
                for name in names.split(","):
                    cleaned = name.strip().split(" as ")[0].strip().strip("()")
                    if cleaned and cleaned != "*":
                        specs.append("." * len(dots) + cleaned)
            continue
        if module:
            specs.append(module)
    for group in _PY_IMPORT.findall(text):
        for module in group.split(","):
            if module.strip():
                specs.append(module.split(" as ")[0].strip())
    return specs


def _js_specs(text: str) -> list[str]:
    return [spec for spec in _JS_IMPORT.findall(text) if spec.startswith(".")]


def _resolve_js(spec: str, source: str, files: set[str]) -> str | None:
    for candidate in _relative_candidates(spec, source):
        if candidate in files:
            return candidate
    return None


def _resolve_python(spec: str, source: str, files: set[str]) -> str | None:
    if spec.startswith("."):
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec.lstrip(".")
        folder = source.rsplit("/", 1)[0] if "/" in source else ""
        parts = folder.split("/") if folder else []
        for _ in range(max(0, dots - 1)):
            if parts:
                parts.pop()
        prefix = "/".join(parts)
        base = rest.replace(".", "/")
        candidate = f"{prefix}/{base}" if prefix else base
        for path in (f"{candidate}.py", f"{candidate}/__init__.py"):
            if path in files:
                return path
        return None
    for candidate in _module_candidates(spec, source):
        if candidate in files:
            return candidate
    return None


def layout(
    ids: list[str],
    *,
    width: float = 1.0,
    height: float = 1.0,
    size_by_id: dict[str, int] | None = None,
) -> dict[str, tuple[float, float]]:
    """Deterministic clustered layout in a 0…1 box.

    Root files sit in a small inner spiral (they are usually the entry points);
    every folder gets a cluster centre on a shared ring, and its files spiral
    around that centre. The shape therefore uses both axes even when a project
    has only two folders, which a pure angular wedge did not.
    """
    if not ids:
        return {}
    groups: dict[str, list[str]] = {}
    for node_id in sorted(ids):
        top = node_id.split("/", 1)[0] if "/" in node_id else ""
        groups.setdefault(top, []).append(node_id)
    root = groups.pop("", [])
    folders = sorted(groups, key=lambda name: (-len(groups[name]), name))
    positions: dict[str, tuple[float, float]] = {}

    def place(cluster_x: float, cluster_y: float, members: list[str], reach: float) -> None:
        # A tight deterministic spiral: golden angle, stable per index.
        for position, node_id in enumerate(members):
            if len(members) == 1:
                offset_r, angle = 0.0, 0.0
            else:
                angle = math.pi * (3 - math.sqrt(5)) * (position + 1)
                offset_r = reach * math.sqrt((position + 1) / len(members))
            jitter = (zlib.crc32(node_id.encode("utf-8")) % 997) / 997.0 * 0.2 + 0.9
            x = cluster_x + math.cos(angle) * offset_r * jitter
            y = cluster_y + math.sin(angle) * offset_r * jitter
            positions[node_id] = (round(min(0.96, max(0.04, x)), 5), round(min(0.96, max(0.04, y)), 5))

    count = len(folders)
    if not count:
        place(0.5, 0.5, root, reach=0.26)
        return positions
    # Root files (entry points, README, configs) get their own bay so they never
    # sit on top of a folder cluster; a single folder still moves off-centre.
    root_x = 0.30 if count == 1 else 0.5
    place(root_x, 0.5, root, reach=min(0.20, 0.07 + 0.025 * len(root)))
    if count == 1:
        centres = [(0.68, 0.5)]
    elif count == 2:
        centres = [(0.30, 0.22), (0.70, 0.78)]
    else:
        ring = 0.30
        centres = [
            (0.5 + math.cos(2 * math.pi * index / count) * ring,
             0.5 + math.sin(2 * math.pi * index / count) * ring)
            for index in range(count)
        ]
    for (centre_x, centre_y), name in zip(centres, folders, strict=True):
        members = groups[name]
        reach = min(0.22, 0.085 + 0.03 * len(members))
        place(centre_x, centre_y, members, reach)
    return positions


def build_atlas(projects: ProjectService, project: Project, *, max_files: int = MAX_FILES) -> Atlas:
    """Read the project and return nodes, resolved import edges and stats."""
    entries = projects.tree(project)
    file_entries = [entry for entry in entries if not entry.is_dir]
    file_entries.sort(key=lambda entry: entry.relative)
    truncated = len(file_entries) > max_files
    selected = file_entries[:max_files]
    files = {entry.relative for entry in selected}

    texts: dict[str, str] = {}
    languages_by_path: dict[str, str] = {}
    line_counts: dict[str, int] = {}
    for entry in selected:
        if entry.size == 0 or entry.size > MAX_TEXT_BYTES:
            continue
        try:
            content = projects.read(project, entry.relative)
        except (AppError, OSError) as exc:  # one unreadable file must not blank the atlas
            logger.debug("atlas_skip path=%s error=%s", entry.relative, exc)
            continue
        if content.binary:
            continue
        texts[entry.relative] = content.text
        languages_by_path[entry.relative] = entry.language or "other"
        line_counts[entry.relative] = len(content.text.splitlines())

    edges: set[tuple[str, str]] = set()
    outgoing: dict[str, int] = {}
    incoming: dict[str, int] = {}
    specs_seen = 0
    for relative, text in texts.items():
        language = languages_by_path.get(relative, "other")
        stripped = _strip_comments(text, language)
        if language in {"python", "javascript", "typescript", "tsx", "jsx"}:
            specs = _python_specs(stripped) if language == "python" else _js_specs(stripped)
        else:
            continue
        for spec in specs:
            specs_seen += 1
            if language == "python":
                target = _resolve_python(spec, relative, files)
            else:
                target = _resolve_js(spec, relative, files)
            if target is None or target == relative:
                continue
            edges.add((relative, target))
    if len(edges) > MAX_EDGES:
        edges = set(sorted(edges)[:MAX_EDGES])

    for source, target in edges:
        outgoing[source] = outgoing.get(source, 0) + 1
        incoming[target] = incoming.get(target, 0) + 1

    size_by_id = {entry.relative: entry.size for entry in selected}
    positions = layout(
        [entry.relative for entry in selected],
        size_by_id=size_by_id,
    )
    node_list: list[AtlasNode] = []
    for entry in selected:
        language = entry.language or "other"
        x, y = positions.get(entry.relative, (0.5, 0.5))
        node_list.append(
            AtlasNode(
                id=entry.relative,
                label=entry.name,
                language=language,
                size=entry.size,
                lines=line_counts.get(entry.relative, 0),
                folder=entry.relative.rsplit("/", 1)[0] if "/" in entry.relative else "",
                incoming=incoming.get(entry.relative, 0),
                outgoing=outgoing.get(entry.relative, 0),
                x=x,
                y=y,
                cluster=0,
                tone=LANGUAGE_TONE.get(language, LANGUAGE_TONE["other"]),
            )
        )

    languages: dict[str, int] = {}
    for entry in selected:
        language = entry.language or "other"
        languages[language] = languages.get(language, 0) + 1
    hubs = sorted(node_list, key=lambda node: (-node.incoming, node.id))[:5]
    orphans = sorted(node.id for node in node_list if node.degree == 0)
    stats = {
        "files": len(selected),
        "edges": len(edges),
        "languages": languages,
        "truncated": truncated,
        "specs": specs_seen,
        "unresolved": max(0, specs_seen - len(edges)),
        "hubs": [{"id": node.id, "incoming": node.incoming} for node in hubs if node.incoming],
        "orphans": orphans[:40],
        "orphan_count": len(orphans),
        "bytes": sum(entry.size for entry in selected),
        "lines": sum(line_counts.values()),
    }
    return Atlas(
        nodes=tuple(node_list),
        edges=tuple(AtlasEdge(source, target) for source, target in sorted(edges)),
        stats=stats,
    )


__all__ = [
    "Atlas",
    "AtlasEdge",
    "AtlasNode",
    "LANGUAGE_TONE",
    "build_atlas",
    "layout",
]
