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
- **`excludes` bewusst minimal.** Ausgeschlossen sind nur `ruff` und `PyInstaller`, die die
  Anwendung nachweislich nicht importiert.

  Frühere Versuche, das Bundle über Ausschlüsse zu verkleinern, sind gescheitert: der
  Ausschluss von `torch.distributed` (zusammen mit `torch.testing` und
  `torch.utils.tensorboard`) führte beim Start zu `ModuleNotFoundError: No module named
  'torch.distributed'` — torch importiert das Modul selbst über `torch.utils.data.dataloader`,
  also bereits bei `import torch`. Ein Modul, das ein Paket intern importiert, darf nicht
  ausgeschlossen werden, auch wenn die eigene Anwendung es nie direkt verwendet.

  Weitere Größenoptimierung ist denkbar (etwa ungenutzte Qt-Module), muss aber jedes Mal mit
  dem Smoke-Test unten überprüft werden — der Fehler zeigt sich erst zur Laufzeit, nicht
  beim Bauen.
- **`copy_metadata` für photutils und astroquery.** photutils ermittelt seine optionalen
  Abhängigkeiten zur Laufzeit über `importlib.metadata.requires("photutils")`. Sind die
  `dist-info`-Metadaten nicht im Bundle, bricht bereits der Import mit
  `PackageNotFoundError: No package metadata was found for photutils` ab. Datendateien
  allein (`collect_data_files`) reichen dafür **nicht** — Metadaten sind ein eigener
  Mechanismus. `recursive=True` nimmt die Metadaten der Abhängigkeiten mit; sie sind winzig
  und schützen vor derselben Falle an anderer Stelle.
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
powershell -ExecutionPolicy Bypass -File scripts\smoke_test_build.ps1
```

Das Skript startet das gebaute Programm und prüft, ob das **Qt-Hauptfenster mit dem Titel
„STELLA"** erscheint.

> **Nicht nur prüfen, ob der Prozess läuft.** Bei `console=False` zeigt PyInstaller im
> Fehlerfall einen modalen Dialog „Unhandled exception in script“ — der hält den Prozess am
> Leben und meldet sogar `Responding=True`. Ein Test, der nur auf „Prozess lebt“ schaut,
> meldet deshalb auch bei einem harten Importfehler Erfolg. Genau so ist hier ein defektes
> Bundle durchgerutscht (fehlende Paket-Metadaten, siehe oben). Der Fenstertitel
> unterscheidet die beiden Fälle zuverlässig.

Aus demselben Grund läuft der Test bewusst **ohne** `QT_QPA_PLATFORM=offscreen`: ohne echtes
Fenster gäbe es keinen Titel zum Prüfen.

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

## Fehlersuche

### Logdatei (erster Anlaufpunkt)

STELLA schreibt bei jedem Lauf ein Protokoll nach:

```
%USERPROFILE%\.stella\logs\stella.log
```

Erreichbar auch über *Hilfe → Logdatei anzeigen*. Die Datei rotiert (max. 2 MB, 3
Sicherungen) und enthält Umgebungsdaten (Python-, Paketversionen, gewähltes Rechengerät),
den Ablauf der einzelnen Schritte mit Laufzeiten sowie **vollständige Tracebacks**.

Das ist im ausgelieferten Paket der einzige brauchbare Kanal: mit `console=False` gibt es
keine Konsole, und der PyInstaller-Fehlerdialog lässt sich nicht kopieren.

Mehr Details liefert:

```bash
set STELLA_LOG_LEVEL=DEBUG
```

Dann werden zusätzlich einzelne Frames, Sternzahlen pro Frame und die Laufzeit je
Vektor-Block protokolliert.

Die Datei ist UTF-8. Windows PowerShell 5.1 liest mit `Get-Content` standardmäßig ANSI und
stellt Umlaute dann falsch dar — in dem Fall `-Encoding utf8` angeben:

```bash
Get-Content $env:USERPROFILE\.stella\logs\stella.log -Encoding utf8 -Tail 50
```

### Konsolen-Build für Startprobleme

Bricht das Programm ab, *bevor* das Logging steht (etwa bei einem fehlenden Modul im
Bundle), hilft ein Build mit sichtbarer Konsole. In `stella.spec` vorübergehend:

```python
console=True,
```

Danach neu bauen und die `.exe` aus einem Terminal starten — der Traceback erscheint direkt.
Da sich nur die EXE-Stufe ändert, ist dieser Neubau deutlich schneller als der erste.
Anschließend nicht vergessen, wieder auf `console=False` zu stellen.

## Verifizierter Stand

Zuletzt gebaut und geprüft auf Windows 11 (Python 3.12, PyInstaller 6.21):

- Bundle-Größe: ca. 704 MB (dominiert von PyTorch)
- `STELLA.exe` startet, das Hauptfenster „STELLA“ erscheint (Smoke-Test bestanden)
- `astroquery.gaia` samt Abhängigkeiten (`requests`, `pyvo`, `bs4`, `html5lib`, `urllib3`,
  `keyring`) im Archiv enthalten
