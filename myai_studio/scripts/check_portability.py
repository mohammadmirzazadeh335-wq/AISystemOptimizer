"""Portability check that can run on any OS.

On Windows 11 it verifies the runtime pieces the app needs. On Linux/macOS it
still exercises the *rules* that decide Windows correctness, so a regression is
caught in CI before anybody copies a build to a Windows machine.

Exit code 0 means every check passed. Nothing here launches the GUI; use
``scripts/windows11_smoke.ps1`` for the full run on a real machine.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from myai.core.platform import (  # noqa: E402
    IS_WINDOWS,
    creation_flags,
    decode_output,
    filename_problem,
    path_problem,
)
from myai.services import toolchains  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def main() -> int:
    print(f"host        : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"python      : {sys.version.split()[0]} at {sys.executable}")
    print(f"windows     : {IS_WINDOWS}")
    print("-" * 78)

    check("Python 3.11+", sys.version_info >= (3, 11), platform.python_version())
    try:
        import PySide6

        check("PySide6 importable", True, PySide6.__version__)
    except Exception as exc:  # noqa: BLE001
        check("PySide6 importable", False, str(exc))

    for module in ("sqlalchemy", "httpx", "cryptography"):
        try:
            imported = __import__(module)
            check(f"{module} importable", True, getattr(imported, "__version__", "installed"))
        except Exception as exc:  # noqa: BLE001
            check(f"{module} importable", False, str(exc))

    # ------------------------------------------------------------ Windows rules
    check("console decode is tolerant", decode_output(b"caf\xe9") == "café")
    check("UTF-16 BOM decoded", decode_output("نمونه".encode("utf-16")) == "نمونه")
    check("reserved name refused", filename_problem("CON.txt") == "reserved")
    check("trailing dot refused", filename_problem("name.") == "trailing")
    check("invalid char refused", filename_problem("a:b") == "invalid_chars")
    check("normal name accepted", filename_problem("main.py") is None)
    check("long path refused", path_problem(["a" * 120] * 3) == "path_too_long")
    check("creation flags sane", creation_flags() == 0 or IS_WINDOWS, str(creation_flags()))

    # --------------------------------------------------------------- toolchains
    available = toolchains.registry().available()
    print("toolchains  : " + (", ".join(item.id for item in available) or "none detected"))
    if IS_WINDOWS:
        check("cmd toolchain offered on Windows", any(item.id == "cmd" for item in toolchains.specs()))
        check("python interpreter resolvable", bool(toolchains.python_executable()))

    # ------------------------------------------------- Windows static rules
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import check_windows_static

        findings = check_windows_static.scan([ROOT / "myai"])
        kinds = sorted({finding.rule for finding in findings})
        check(
            "source has no Windows hazards",
            not findings,
            "clean" if not findings else f"{len(findings)} finding(s): {', '.join(kinds)}",
        )
    except Exception as exc:  # noqa: BLE001 - the check itself must not crash the run
        check("source has no Windows hazards", False, f"scanner failed: {exc}")

    # ------------------------------------------------------------- entry points
    check("launcher entry point", callable(__import__("myai.app", fromlist=["main"]).main))
    check("assets folder present", (ROOT / "assets").is_dir())
    check("locale catalogues present",
          all((ROOT / "myai" / "i18n" / "locales" / f"{lang}.json").is_file() for lang in ("en", "fa")))

    print("-" * 78)
    failures = 0
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<32} {detail}")
        failures += 0 if ok else 1
    print("-" * 78)
    print(f"{len(RESULTS) - failures}/{len(RESULTS)} checks passed")
    if not IS_WINDOWS:
        print("note: this host is not Windows; the GUI smoke test must run on Windows 11.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
