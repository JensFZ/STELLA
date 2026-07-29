# Build & Packaging (PLAN.md Phase 8)

Erzeugt aus dem Quellbaum eine lauffähige Anwendung ohne Python-Installation beim
Endnutzer. Gebaut wird jeweils für die Plattform, auf der der Build läuft — PyInstaller
kann nicht cross-kompilieren.

## Entwicklungsumgebung einrichten

```bash
python -m venv .venv
```

```bash
.venv\Scripts\pip install -e ".[dev,packaging]"
```

## Build erzeugen

```bash
.venv\Scripts\pyinstaller stella.spec --noconfirm
```

Ergebnis: `dist/STELLA/STELLA.exe` samt Abhängigkeiten im selben Ordner. Der komplette
Ordner ist das Auslieferungspaket und muss zusammen weitergegeben werden.

## Entscheidungen in `stella.spec`

- **Kein `--onefile`.** Das Bundle enthält PyTorch und ist mehrere hundert MB groß. Ein
  Ein-Datei-Build müsste dieses Volumen bei *jedem* Start in ein temporäres Verzeichnis
  entpacken, was den Programmstart spürbar verzögert.
- **`console=False`.** STELLA ist laut Vorgabe ein reines GUI-Programm; ein zusätzliches
  Konsolenfenster wäre nur störend. Für die Fehlersuche kann der Wert temporär auf `True`
  gesetzt werden, dann erscheinen Tracebacks im Terminal.
- **Explizite `collect_data_files` / `collect_submodules`** für `astroquery` und
  `photutils`: beide laden Konfigurationsdaten zur Laufzeit und lösen Teile ihrer Importe
  dynamisch auf, die der statische Import-Scanner von PyInstaller nicht findet. Für
  `astropy`, `astropy_iers_data`, `torch` und `PySide6` bringt PyInstaller eigene Hooks
  mit, die das bereits abdecken.
- **`excludes`** für ungenutzte Qt-Module (WebEngine, 3D, Multimedia, QML) sowie für
  Torch-Test- und Compiler-Infrastruktur. STELLA nutzt von Torch nur Tensor-Operationen
  und `grid_sample`.
- **matplotlib als reine Build-Abhängigkeit** (im Extra `packaging`). STELLA verwendet
  matplotlib nicht direkt, `photutils` importiert aber `astropy.visualization`, das
  matplotlib-gestützt ist. PyInstaller importiert beim Analysieren jedes gesammelte Paket
  — ohne installiertes matplotlib bricht der Build dort mit
  `Skipped: could not import 'matplotlib'` ab.

  Zu beachten, falls dieser Fehler wieder auftritt: `collect_submodules(..., on_error=
  "ignore")` hilft **nicht**. `astropy.visualization.wcsaxes` nutzt
  `pytest.importorskip`, das die Ausnahme `Skipped` wirft — die erbt von `BaseException`
  und läuft daher an PyInstallers Fehlerbehandlung (die `Exception` abfängt) vorbei.

## Bekannte Einschränkungen

- **Erststart dauert länger.** Beim ersten Start legt `astropy` seinen Cache an; zusätzlich
  prüft es IERS-Zeitdaten. Ohne Netzwerkzugriff funktioniert das weiterhin, astropy fällt
  dann auf die mitgelieferten Tabellen zurück.
- **Gaia-Abfrage braucht Internet.** Die Astrometrie (Menü *Projekt → Astrometrie
  berechnen*) fragt den Gaia-Katalog online ab. Alle anderen Funktionen — Import, Viewer,
  Alignment, Suche, Detektion — laufen vollständig offline.
- **GPU-Unterstützung richtet sich nach dem installierten PyTorch.** Wird im Build-venv
  ein CPU-only-Wheel verwendet (Standard von PyPI auf Rechnern ohne CUDA), enthält auch
  das Bundle nur den CPU-Pfad. Für ein Paket mit CUDA-Unterstützung muss vor dem Build ein
  passendes CUDA-Wheel installiert werden:

  ```bash
  .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
  ```

- **Multiplatform-Builds** (Linux, macOS) sind laut PLAN.md optional und nicht umgesetzt.
  Sie erfordern jeweils einen Build auf der Zielplattform mit demselben `stella.spec`.

## Smoke-Test nach dem Build

```bash
dist\STELLA\STELLA.exe
```

Das Hauptfenster muss erscheinen; über *Datei → FITS-Ordner öffnen* lässt sich ein
Bildstapel laden. Ein automatisierter Start-Check ohne sichtbares Fenster ist über die
Umgebungsvariable `QT_QPA_PLATFORM=offscreen` möglich.

Ein erfolgreicher Start deckt bereits einen Großteil des Bundles ab: das Fenster erscheint
erst, wenn `main.py` → `gui.main_window` → `gui.workers` → `core.*` vollständig importiert
sind, also PySide6, numpy, astropy, photutils, scipy und torch geladen wurden.

`astroquery` wird davon **nicht** erfasst — es wird erst beim tatsächlichen Gaia-Abruf
importiert (`core/astrometry.py`). Ob es im Bundle liegt, lässt sich ohne Netzwerkzugriff
im Archiv prüfen:

```bash
.venv\Scripts\pyi-archive_viewer -b -r -l dist\STELLA\STELLA.exe
```

Reine Python-Pakete liegen im PYZ-Archiv, nicht als Ordner unter `_internal/` — ein Blick
ins Dateisystem allein ist daher irreführend.

## Verifizierter Stand

Zuletzt gebaut und geprüft auf Windows 11 (Python 3.12, PyInstaller 6.21):

- Bundle-Größe: ca. 689 MB (dominiert von PyTorch)
- `STELLA.exe` startet und bleibt stabil (Smoke-Test bestanden)
- `astroquery.gaia` samt Abhängigkeiten (`requests`, `pyvo`, `bs4`, `html5lib`, `urllib3`,
  `keyring`) im Archiv enthalten
