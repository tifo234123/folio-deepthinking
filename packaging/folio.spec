# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Folio Deepthinking: a single-file Windows .exe (also builds on Linux).

Build from the project root:  pyinstaller packaging/folio.spec --noconfirm
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
ICON = ROOT / "packaging" / "folio.ico"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "folio" / "prompts"), "folio/prompts"),
           (str(ROOT / "folio" / "static"), "folio/static")],
    hiddenimports=collect_submodules("folio") + ["PySide6.QtSvg", "PySide6.QtSvgWidgets"],
    # Unused Qt modules; keeps the download far smaller.
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtBluetooth", "PySide6.QtSensors",
              "PySide6.QtSerialPort", "PySide6.QtTest", "PySide6.QtDesigner"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# One self-contained executable: dist/FolioDeepthinking.exe (no _internal folder).
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="FolioDeepthinking",
    console=False,
    upx=False,
    icon=str(ICON) if sys.platform == "win32" and ICON.exists() else None,
)
