#!/usr/bin/env python3
"""Static checks for Windows 11 compatibility of the source tree.

This is not a substitute for running on Windows — nothing on this Linux host
is. It is the part that *can* be proven here and is easy to regress: the code
must not import POSIX-only modules at import time, must not spawn a child
process without hiding its console, must not write text with the locale code
page, and must not use a POSIX-only process API outside a platform guard.

Each rule is a small AST query, and each has a negative test in
``tests/unit/test_windows_static.py`` that feeds it bad code, so a rule that
stops working is visible immediately.

Usage:
    python scripts/check_windows_static.py [path ...]     # default: myai/
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Modules that do not exist on Windows. Importing one at module scope would
#: make the whole app fail to start; importing it inside a platform-guarded
#: function is fine and is therefore allowed.
POSIX_ONLY = {
    "fcntl", "grp", "pwd", "resource", "syslog", "termios", "tty", "pty",
    "crypt", "spwd", "posix", "nis", "ossaudiodev", "readline",
}

SPAWN_FUNCTIONS = {"Popen", "run", "call", "check_output", "check_call"}
WRITE_MODES = set("wax+")
POSIX_APIS = {"fork", "forkpty", "setsid", "getuid", "geteuid", "chroot", "setuid", "killpg"}
PATH_LITERALS = ("/tmp/", "/usr/bin/", "/usr/local/bin/", "/bin/sh", "/bin/bash", "/etc/")
GUARD_MARKERS = ("IS_WINDOWS", "os.name ==", 'os.name == "nt"', 'sys.platform.startswith("win")',
                 'sys.platform == "win32"', "IS_FROZEN")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    table: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[child] = node
    return table


def _enclosing_functions(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    chain: list[ast.AST] = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            chain.append(current)
        current = parents.get(current)
    return chain


def _source(node: ast.AST, text: str) -> str:
    segment = ast.get_source_segment(text, node)
    return segment or ""


def _module_level(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return False
        current = parents.get(current)
    return True


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr in SPAWN_FUNCTIONS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
    return isinstance(func, ast.Name) and func.id in SPAWN_FUNCTIONS


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((item for item in call.keywords if item.arg == name), None)


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def scan_file(path: Path, text: str | None = None) -> list[Finding]:
    relative = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    source = text if text is not None else path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("syntax", relative, exc.lineno or 0, f"cannot parse: {exc.msg}")]
    parents = _parents(tree)
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [alias.name.split(".")[0] for alias in node.names]
                if isinstance(node, ast.Import)
                else [(node.module or "").split(".")[0]]
            )
            for name in names:
                if name in POSIX_ONLY and _module_level(node, parents):
                    findings.append(
                        Finding(
                            "posix-import",
                            relative,
                            node.lineno,
                            f"'{name}' does not exist on Windows; import it inside a "
                            "platform-guarded function instead",
                        )
                    )

        elif isinstance(node, ast.Call):
            if _is_subprocess_call(node):
                if _keyword(node, "creationflags") is None:
                    findings.append(
                        Finding(
                            "console-window",
                            relative,
                            node.lineno,
                            "subprocess call without creationflags=creation_flags() "
                            "would flash a console window on Windows",
                        )
                    )
                shell = _keyword(node, "shell")
                if (
                    shell is not None
                    and isinstance(shell.value, ast.Constant)
                    and shell.value.value is True
                ):
                    findings.append(
                        Finding("shell", relative, node.lineno, "shell=True is not portable")
                    )
            name = _call_name(node)
            if name in {"open", "write_text", "read_text"}:
                mode = ""
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        mode = arg.value
                mode_kw = _keyword(node, "mode")
                if mode_kw is not None and isinstance(mode_kw.value, ast.Constant):
                    mode = str(mode_kw.value.value or "")
                is_write = name in {"write_text"} or any(char in mode for char in WRITE_MODES)
                if name == "open" and not mode:
                    is_write = False
                if (is_write or name == "read_text") and _keyword(node, "encoding") is None:
                    findings.append(
                        Finding(
                            "encoding",
                            relative,
                            node.lineno,
                            f"{name}() without encoding= uses the Windows code page "
                            "(cp1252) and mangles non-Latin text",
                        )
                    )
            if name in POSIX_APIS:
                guarded = False
                for function in _enclosing_functions(node, parents):
                    segment = _source(function, source)
                    if any(marker in segment for marker in GUARD_MARKERS):
                        guarded = True
                        break
                if not guarded:
                    findings.append(
                        Finding(
                            "posix-api",
                            relative,
                            node.lineno,
                            f"os.{name}() only exists on POSIX and is not inside a "
                            "platform guard",
                        )
                    )

        elif isinstance(node, ast.Attribute):
            if (
                node.attr == "SIGKILL"
                and isinstance(node.value, ast.Name)
                and node.value.id == "signal"
            ):
                guarded = any(
                    any(marker in _source(function, source) for marker in GUARD_MARKERS)
                    for function in _enclosing_functions(node, parents)
                )
                if not guarded:
                    findings.append(
                        Finding(
                            "posix-api",
                            relative,
                            node.lineno,
                            "signal.SIGKILL does not exist on Windows and is not inside "
                            "a platform guard",
                        )
                    )
            # sys.executable as a child command. Reading it for display is fine;
            # launching it is not (in a frozen build it is the app itself).
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "sys"
                and node.attr == "executable"
                and not _inside_python_executable(node, parents, source)
                and "platform.py" not in relative
            ):
                findings.append(
                    Finding(
                        "frozen-interpreter",
                        relative,
                        node.lineno,
                        "sys.executable is the app itself in a frozen build; use "
                        "toolchains.python_executable()",
                    )
                )

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if any(value.startswith(prefix) for prefix in PATH_LITERALS):
                findings.append(
                    Finding(
                        "posix-path",
                        relative,
                        node.lineno,
                        f"hard-coded POSIX path {value[:40]!r} does not exist on Windows",
                    )
                )

    return findings


def _inside_python_executable(node: ast.AST, parents: dict[ast.AST, ast.AST], source: str) -> bool:
    for function in _enclosing_functions(node, parents):
        if isinstance(function, ast.FunctionDef) and function.name == "python_executable":
            return True
    return False


def scan(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for base in paths:
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in files:
            if "__pycache__" in path.parts:
                continue
            findings.extend(scan_file(path))
    return findings


def main(argv: list[str]) -> int:
    targets = [Path(item).resolve() for item in argv[1:]] or [ROOT / "myai"]
    findings = scan(targets)
    print("Windows static compatibility (source level)")
    print("-" * 74)
    rules = ["posix-import", "console-window", "shell", "encoding", "posix-api",
             "frozen-interpreter", "posix-path", "syntax"]
    for rule in rules:
        count = sum(1 for finding in findings if finding.rule == rule)
        status = "PASS" if count == 0 else "FAIL"
        print(f"[{status}] {rule:<20} {count} finding(s)")
    if findings:
        print("-" * 74)
        for finding in findings[:40]:
            print(f"  {finding}")
        if len(findings) > 40:
            print(f"  … {len(findings) - 40} more")
        print("-" * 74)
        print(f"{len(findings)} problem(s). These would fail or misbehave on Windows 11.")
        return 1
    print("-" * 74)
    print("No platform hazard found.")
    print("note: this proves the rules, not a Windows run; run scripts/windows11_smoke.ps1 there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
