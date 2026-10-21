"""Real toolchain discovery.

Nothing here guesses: a toolchain is only reported as available when its binary is
found on ``PATH`` **and** answers a ``--version`` (or equivalent) probe. Everything
else is reported as unavailable together with the executable that is missing, so the
UI can say exactly why a language cannot be run on this machine.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: How long a version probe may take. A tool that hangs is treated as unavailable.
PROBE_TIMEOUT = 6.0


@dataclass(frozen=True)
class Toolchain:
    id: str
    label: str
    available: bool
    version: str = ""
    detail: str = ""
    executables: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "available": self.available,
            "version": self.version,
            "detail": self.detail,
            "executables": list(self.executables),
            "extensions": list(self.extensions),
        }


@dataclass
class RunStep:
    """One process to execute: a compile step or the program itself."""

    label: str
    argv: list[str]
    kind: str = "run"  # "compile" | "run"


@dataclass
class RunPlan:
    language: str
    label: str
    toolchain: str
    steps: list[RunStep]
    cwd: Path
    source: Path
    artifacts: list[Path] = field(default_factory=list)
    timeout_seconds: float = 10.0

    @property
    def command(self) -> str:
        return " && ".join(" ".join(step.argv) for step in self.steps)


class ToolchainUnavailable(RuntimeError):
    """Raised when a file cannot be run because the toolchain is missing."""

    def __init__(self, toolchain: str, detail: str) -> None:
        super().__init__(detail or f"{toolchain} is not available on this machine")
        self.toolchain = toolchain
        self.detail = detail or f"{toolchain} is not available on this machine"


def _probe(argv: list[str]) -> tuple[bool, str]:
    """Run a version probe; return (ok, first non-empty line)."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    output = (completed.stdout or "") + (completed.stderr or "")
    text = next((line.strip() for line in output.splitlines() if line.strip()), "")
    return completed.returncode == 0, text


def _find(candidates: list[str]) -> str:
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return ""


#: (id, label, candidates, version argv suffix, extensions)
SPECS = (
    ("python", "Python", ["python3", "python"], ["--version"], (".py",)),
    ("node", "Node.js", ["node"], ["--version"], (".js", ".mjs", ".cjs")),
    ("c", "C", ["gcc", "clang", "cc"], ["--version"], (".c",)),
    ("cpp", "C++", ["g++", "clang++", "c++"], ["--version"], (".cpp", ".cc", ".cxx")),
    ("java", "Java", ["java"], ["-version"], (".java",)),
    ("dotnet", ".NET", ["dotnet"], ["--version"], (".cs",)),
    ("go", "Go", ["go"], ["version"], (".go",)),
    ("rust", "Rust", ["rustc"], ["--version"], (".rs",)),
    ("bash", "Bash", ["bash"], ["--version"], (".sh",)),
    ("powershell", "PowerShell", ["pwsh", "powershell"], ["-Version"], (".ps1",)),
)


class ToolchainRegistry:
    """Cached, thread-safe detection of the toolchains on this machine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, Toolchain] | None = None

    # ------------------------------------------------------------------ public
    def detect(self, *, refresh: bool = False) -> list[Toolchain]:
        with self._lock:
            if self._items is None or refresh:
                self._items = {item.id: item for item in self._detect_all()}
            return list(self._items.values())

    def get(self, toolchain_id: str) -> Toolchain | None:
        self.detect()
        assert self._items is not None
        return self._items.get(toolchain_id)

    def for_extension(self, extension: str) -> Toolchain | None:
        extension = extension.lower()
        for item in self.detect():
            if extension in item.extensions and item.available:
                return item
        for item in self.detect():
            if extension in item.extensions:
                return item
        return None

    def available(self) -> list[Toolchain]:
        return [item for item in self.detect() if item.available]

    def summary(self) -> dict:
        items = self.detect()
        return {
            "available": [item.id for item in items if item.available],
            "missing": [item.id for item in items if not item.available],
            "count": sum(1 for item in items if item.available),
        }

    # ----------------------------------------------------------------- internal
    def _detect_all(self) -> list[Toolchain]:
        results: list[Toolchain] = []
        for toolchain_id, label, candidates, version_args, extensions in SPECS:
            found = _find(candidates)
            if not found:
                results.append(
                    Toolchain(
                        id=toolchain_id,
                        label=label,
                        available=False,
                        detail=f"{candidates[0]} was not found on PATH",
                        extensions=extensions,
                    )
                )
                continue
            ok, version = _probe([found, *version_args])
            if not ok:
                results.append(
                    Toolchain(
                        id=toolchain_id,
                        label=label,
                        available=False,
                        detail=f"{Path(found).name} exists but did not answer "
                        f"'{version_args[0]}'",
                        executables=(found,),
                        extensions=extensions,
                    )
                )
                continue
            results.append(
                Toolchain(
                    id=toolchain_id,
                    label=label,
                    available=True,
                    version=version,
                    executables=(found,),
                    extensions=extensions,
                )
            )
        logger.info(
            "toolchains_detected available=%s",
            ",".join(item.id for item in results if item.available) or "none",
        )
        return results


_registry: ToolchainRegistry | None = None


def registry() -> ToolchainRegistry:
    global _registry
    if _registry is None:
        _registry = ToolchainRegistry()
    return _registry


def python_executable() -> str:
    """The interpreter running the app — preferred over ``python`` on PATH.

    ``sys.executable`` keeps whatever spelling launched the app (often
    ``.venv/bin/python`` behind ``../``), which then appears verbatim in the
    command line shown to the user; the real path is the same interpreter and
    reads as a real command.
    """
    if sys.executable:
        return os.path.realpath(sys.executable)
    return _find(["python3", "python"])


def build_plan(source: Path, *, cwd: Path, timeout_seconds: float = 10.0) -> RunPlan:
    """Return the exact steps needed to run ``source``.

    Raises :class:`ToolchainUnavailable` with a precise reason when this machine
    cannot run the file. No plan is ever produced for a missing toolchain.
    """
    source = Path(source)
    suffix = source.suffix.lower()
    toolchain = registry().for_extension(suffix)
    if toolchain is None:
        raise ToolchainUnavailable(
            "unknown", f"No toolchain is configured for '{suffix or source.name}'"
        )
    if toolchain.id == "java":
        # A .java file needs both halves of the JDK; say exactly which one is
        # absent instead of the generic "java was not found on PATH".
        missing = [name for name in ("javac", "java") if shutil.which(name) is None]
        if missing:
            raise ToolchainUnavailable(
                "java",
                f"{' and '.join(missing)} not found on PATH "
                "(Java needs javac to compile and java to run)",
            )
    if not toolchain.available:
        raise ToolchainUnavailable(toolchain.id, toolchain.detail)

    exe = toolchain.executables[0] if toolchain.executables else ""
    name = source.name
    stem = source.stem
    build_dir = Path(cwd) / ".myai-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    if toolchain.id == "python":
        argv = [python_executable(), "-u", name]
        steps = [RunStep("run", argv)]
    elif toolchain.id == "node":
        steps = [RunStep("run", [exe, name])]
    elif toolchain.id in {"c", "cpp"}:
        binary = build_dir / (stem + (".exe" if os.name == "nt" else ""))
        artifacts.append(binary)
        steps = [
            RunStep("compile", [exe, "-O0", "-g", "-Wall", "-Wextra", "-o", str(binary), name], "compile"),
            RunStep("run", [str(binary)]),
        ]
    elif toolchain.id == "java":
        class_dir = build_dir
        artifacts.append(class_dir)
        javac = shutil.which("javac")
        if not javac:
            raise ToolchainUnavailable("java", "javac is required to compile Java and was not found on PATH")
        steps = [
            RunStep("compile", [javac, "-d", str(class_dir), name], "compile"),
            RunStep("run", [exe, "-cp", str(class_dir), stem]),
        ]
    elif toolchain.id == "dotnet":
        steps = [
            RunStep(
                "compile",
                [exe, "run", "--project", name],
                "compile",
            )
        ]
    elif toolchain.id == "go":
        steps = [RunStep("run", [exe, "run", name])]
    elif toolchain.id == "rust":
        binary = build_dir / (stem + (".exe" if os.name == "nt" else ""))
        artifacts.append(binary)
        steps = [
            RunStep("compile", [exe, "-o", str(binary), name], "compile"),
            RunStep("run", [str(binary)]),
        ]
    elif toolchain.id == "bash":
        steps = [RunStep("run", [exe, name])]
    elif toolchain.id == "powershell":
        steps = [RunStep("run", [exe, "-NoProfile", "-File", name])]
    else:  # pragma: no cover - defensive
        raise ToolchainUnavailable(toolchain.id, f"No runner for {toolchain.label}")

    return RunPlan(
        language=toolchain.id,
        label=toolchain.label,
        toolchain=toolchain.id,
        steps=steps,
        cwd=Path(cwd),
        source=source,
        artifacts=artifacts,
        timeout_seconds=timeout_seconds,
    )
