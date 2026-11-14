# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for «زرین هرمز» (Zarrin Hormoz).

Build on Windows 10/11 with:

    py -3.11 -m pip install -r requirements.txt pyinstaller==6.11.1
    py -3.11 -m PyInstaller packaging/zarrin_hormoz.spec --noconfirm

The result is ``dist/ZarrinHormoz/ZarrinHormoz.exe``; the Inno Setup script
``packaging/zarrin_hormoz.iss`` turns that folder into the installer.

Notes
-----
* Qt is collected with the plugins the application actually loads (``platforms``,
  ``styles``, ``imageformats``, ``iconengines``); ``QtPdf`` is kept because the
  report centre uses it to verify exported PDFs.
* The Persian font (Vazirmatn) and the SVG icons are data files, not code, and
  must be listed explicitly or they disappear from the frozen build.
* No secrets are embedded: the database and the configuration live in the user
  data folder (``%LOCALAPPDATA%\\ZarrinHormoz`` by default), never next to the
  executable.
"""

from pathlib import Path

import sys

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
PACKAGE = SRC / "pars_erp"

datas = [
    (str(PACKAGE / "resources"), "pars_erp/resources"),
    (str(PACKAGE / "migrations"), "pars_erp/migrations"),
    (str(ROOT / "alembic.ini"), "."),
    (str(ROOT / "docs"), "docs"),
]

hiddenimports = [
    "pars_erp",
    "pars_erp.app",
    "pars_erp.cli",
    "pars_erp.migrations.env",
    "alembic",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "PySide6.QtPdf",
    "PySide6.QtSvg",
    "openpyxl",
    "argon2",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
]

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "pytest",
    "tests",
    "PySide6.QtWebEngineCore",
    "PySide6.QtQuick",
    "PySide6.Qt3DCore",
]

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZarrinHormoz",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "packaging" / "zarrin_hormoz.ico")
    if (ROOT / "packaging" / "zarrin_hormoz.ico").exists() else None,
)

# A console variant is shipped as well: support staff run ``doctor``, ``backup``
# and ``report`` from it, and it is what the updater script calls.
console_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZarrinHormoz-console",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ROOT / "packaging" / "zarrin_hormoz.ico")
    if (ROOT / "packaging" / "zarrin_hormoz.ico").exists() else None,
)

coll = COLLECT(
    exe,
    console_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ZarrinHormoz",
)
