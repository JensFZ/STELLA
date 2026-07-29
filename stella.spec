# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für STELLA (PLAN.md Phase 8).

Build:
    pyinstaller stella.spec --noconfirm

Erzeugt einen Ordner `dist/STELLA/` mit `STELLA.exe`. Bewusst kein --onefile:
das Bundle enthält PyTorch und ist mehrere hundert MB groß, ein Ein-Datei-Build
müsste das bei jedem Start erst entpacken und würde entsprechend lange brauchen.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

# Für astropy, astropy_iers_data, torch und PySide6 bringt PyInstaller eigene Hooks mit;
# die decken Datendateien und dynamische Importe dieser Pakete bereits ab.
#
# astroquery und photutils haben keine Hooks: sie laden Konfigurationsdaten zur Laufzeit
# und lösen Teile ihrer Importe dynamisch auf. `on_error="ignore"` ist hier nötig, weil
# beide Pakete optionale Submodule enthalten, die zusätzliche, für STELLA nicht benötigte
# Abhängigkeiten verlangen (z.B. matplotlib) und beim Einsammeln sonst den Build abbrechen.
for package in ("astroquery", "photutils"):
    datas += collect_data_files(package)
    hiddenimports += collect_submodules(package, on_error="ignore")

# pyerfa bringt Zeit-/Koordinaten-Tabellen mit, die astropy zur Laufzeit erwartet.
datas += collect_data_files("erfa")

excludes = [
    # Reine Entwicklungs-/Testabhängigkeiten gehören nicht ins Auslieferungspaket.
    "pytest",
    "ruff",
    "PyInstaller",
    # Nicht genutzte Qt-Module: sparen im Bundle deutlich Platz.
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    # Torch bringt Test- und Compiler-Infrastruktur mit, die zur Laufzeit nicht
    # gebraucht wird (STELLA nutzt nur Tensor-Operationen und grid_sample).
    "torch.distributed",
    "torch.testing",
    "torch.utils.tensorboard",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
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
    name="STELLA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="STELLA",
)
