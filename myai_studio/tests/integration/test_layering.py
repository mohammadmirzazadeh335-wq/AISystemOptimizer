"""Architecture guard rails: the core must stay UI-free and import-clean."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "myai"

QT_FREE_PACKAGES = ("core", "data", "services", "security", "i18n")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = "." * node.level + module
            found.add(module)
    return found


@pytest.mark.parametrize("package", QT_FREE_PACKAGES)
def test_core_packages_do_not_import_qt(package: str) -> None:
    offenders = []
    for path in (ROOT / package).rglob("*.py"):
        for module in _imports(path):
            if module.split(".")[0] in {"PySide6", "shiboken6"} or module.startswith("..ui"):
                offenders.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not offenders, offenders


def test_ui_modules_never_import_services_directly_beyond_contract() -> None:
    """UI may use services, but services must not reach back into ui."""
    offenders = []
    for path in (ROOT / "services").rglob("*.py"):
        for module in _imports(path):
            if ".ui" in module:
                offenders.append(f"{path.name} -> {module}")
    assert not offenders


def test_every_module_compiles() -> None:
    import py_compile

    for path in ROOT.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)
