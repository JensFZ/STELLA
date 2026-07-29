# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für STELLA (PLAN.md Phase 8).

Build:
    pyinstaller stella.spec --noconfirm

Erzeugt einen Ordner `dist/STELLA/` mit `STELLA.exe`. Bewusst kein --onefile:
das Bundle enthält PyTorch und ist mehrere hundert MB groß, ein Ein-Datei-Build
müsste das bei jedem Start erst entpacken und würde entsprechend lange brauchen.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

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

# Paket-Metadaten (dist-info) müssen mit ins Bundle: photutils ermittelt seine optionalen
# Abhängigkeiten zur Laufzeit über importlib.metadata.requires("photutils") und bricht
# ohne die Metadaten schon beim Import mit PackageNotFoundError ab. `recursive=True`
# nimmt die Metadaten der Abhängigkeiten gleich mit — sie sind winzig und schützen vor
# derselben Falle an anderer Stelle.
for package in ("photutils", "astroquery"):
    datas += copy_metadata(package, recursive=True)

# pyerfa bringt Zeit-/Koordinaten-Tabellen mit, die astropy zur Laufzeit erwartet.
datas += collect_data_files("erfa")

# Kompilierte Übersetzungen. Ohne sie bliebe die Oberfläche im gebauten Paket immer in der
# Quellsprache, obwohl die Sprachwahl im Menü angeboten wird. Die .ts-Quelldateien werden
# bewusst nicht mitgeliefert — sie werden nur zum Erzeugen der .qm gebraucht.
datas += [(str(Path("i18n") / "stella_en.qm"), "i18n")]

# Ausschlüsse sind bewusst zurückhaltend gehalten. Ein Ausschluss spart nur dann Platz,
# wenn das Modul wirklich ungenutzt ist — importiert das Paket es intern, bricht die
# Anwendung erst zur Laufzeit ab.
#
# Nicht ausschließen: Teilmodule von torch. Ein Versuch, `torch.distributed`,
# `torch.testing` und `torch.utils.tensorboard` herauszunehmen, führte zu
# `ModuleNotFoundError: No module named 'torch.distributed'` beim Start — torch importiert
# das Modul selbst über `torch.utils.data.dataloader`, also schon bei `import torch`.
excludes = [
    # Reine Entwicklungs-/Testwerkzeuge, von der Anwendung nicht importiert.
    "ruff",
    "PyInstaller",
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
