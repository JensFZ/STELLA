# STELLA

**S**ynthetic **T**racking **E**ngine for **L**ocating & **L**ogging **A**steroids

Ein Desktop-Werkzeug, das lichtschwache und schnell bewegte Asteroiden in Serien von
Astro-Aufnahmen findet — mittels **Synthetic Tracking** (Shift-and-Stack über hypothetische
Bewegungsvektoren) — und die Treffer astrometrisch gegen den Gaia-Katalog vermisst.

Ein Objekt, das sich zwischen den Einzelaufnahmen bewegt, verschmiert bei normalem Stacking
und verschwindet im Rauschen. Synthetic Tracking dreht das um: die Frames werden entlang
*angenommener* Bewegungsvektoren gegeneinander verschoben und aufsummiert. Passt ein Vektor
zur tatsächlichen Bewegung, addiert sich das Objekt konstruktiv auf und hebt sich vom
Hintergrund ab — während Sterne verschmieren.

STELLA ist eine offene Alternative zu Tycho Tracker.

## Status

Alle Phasen des Entwicklungsplans ([PLAN.md](PLAN.md)) sind umgesetzt: FITS-Import und
Viewer, Sternfeld-Alignment, Synthetic-Tracking-Kern (CPU und GPU), Detektion mit
Kandidaten-UI, Gaia-Astrometrie mit MPC-Export, Projektpersistenz und Packaging.

**Wichtige Einschränkung:** Verifiziert wurde bisher ausschließlich mit synthetischen
Testaufnahmen — teils an realen Himmelspositionen mit echten Gaia-Katalogdaten, aber ohne
echte Teleskopdaten. Rauschverhalten, Nachführfehler und optische Verzeichnungen realer
Aufnahmen können sich anders verhalten. Wer STELLA an echten Daten einsetzt, sollte die
Ergebnisse zunächst kritisch gegenprüfen.

## Funktionsumfang

- **FITS-Import** ganzer Ordner, inklusive Header- und WCS-Auswertung
- **Viewer** mit Zoom, Histogramm-Stretch, Thumbnail-Leiste und Frame-Blink
- **Alignment**: Sternerkennung via photutils, Registrierung aller Frames auf einen
  Referenzframe, erkannte Sterne als Overlay
- **Synthetic Tracking** über ein konfigurierbares Gitter aus Geschwindigkeit × Richtung,
  wahlweise als NumPy/SciPy-Referenz oder gebatcht über PyTorch (CUDA/MPS, sonst CPU)
- **Detektion**: SNR-Peak-Suche, Duplikatreduktion, sortierbare Kandidatenliste mit
  Vorschaubild und manueller Bestätigung
- **Astrometrie**: Gaia-Abfrage, Cross-Matching, WCS-Fit mit Residuen-Anzeige
- **Export** im MPC-80-Spalten-Format, mit einer Beobachtungszeile je Frame
- **Projekte**: Sitzungen und Suchparameter-Presets in SQLite

## Installation

Voraussetzung ist Python 3.11 oder neuer.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\pip install -e ".[dev]"
```

Starten:

```bash
.venv\Scripts\python main.py
```

Ein eigenständiges Programmpaket ohne Python-Installation lässt sich mit PyInstaller bauen
— siehe [BUILD.md](BUILD.md).

## Arbeitsablauf

Die Menüpunkte werden nacheinander freigeschaltet, da jeder Schritt auf dem vorherigen
aufbaut.

1. **Datei → FITS-Ordner öffnen** (`Strg+O`) lädt einen Bildstapel. Erwartet werden bereits
   kalibrierte Aufnahmen (Darks/Flats abgezogen) mit `DATE-OBS` im Header — die Zeitstempel
   sind für die Bewegungsrechnung zwingend.
2. **Projekt → Sterne erkennen & ausrichten** registriert alle Frames auf den ersten Frame
   und gleicht damit die Nachführdrift aus.
3. **Projekt → Kandidaten suchen** öffnet die Suchparameter. Der Suchraum sollte zur
   erwarteten Objektgeschwindigkeit passen: ein zu weites Gitter kostet viel Rechenzeit, ein
   zu grobes Gitter verfehlt das Objekt.
4. **Kandidaten sichten.** Falsch-Positive sind bei diesem Verfahren normal und werden
   bewusst nicht automatisch gefiltert — helle Sterne erzeugen regelmäßig stärkere Treffer
   als das gesuchte Objekt. Jeder Kandidat wird per Dropdown auf *Bestätigt* oder
   *Verworfen* gesetzt.
5. **Projekt → Astrometrie berechnen** fragt Gaia ab und passt die WCS an. Das Feldzentrum
   wird aus dem Header vorbelegt, sofern vorhanden. *Benötigt Internetzugang.*
6. **Projekt → MPC-Report exportieren** schreibt die bestätigten Kandidaten heraus, mit
   einer Zeile pro Frame.

Über **Projekt → Neues Projekt** bzw. **Projekt öffnen** lassen sich Sitzungen samt
Kandidatenbewertung speichern und später fortsetzen.

> **Vor einer echten MPC-Einreichung:** Der Export enthält Platzhalter für die provisorische
> Objektbezeichnung und den Stationscode (`XXX`). Beide müssen durch die offiziell
> zugewiesenen Werte ersetzt werden — siehe [core/mpc_report.py](core/mpc_report.py).

## Fehlersuche

STELLA protokolliert jeden Lauf nach `~/.stella/logs/stella.log` — unter Windows also
`%USERPROFILE%\.stella\logs\stella.log`. Am schnellsten erreichbar über *Hilfe → Logdatei
anzeigen*.

Das Protokoll enthält die Umgebung (Python- und Paketversionen, gewähltes Rechengerät), den
Ablauf jedes Schritts mit Laufzeiten und Kennzahlen (erkannte Sterne, Drift je Frame, Anzahl
Kandidaten, Gaia-Matches, RMS-Residuum) sowie vollständige Tracebacks bei Fehlern. Bei einem
Problem ist diese Datei das Erste, was weiterhilft.

Ausführlicher wird es mit:

```bash
set STELLA_LOG_LEVEL=DEBUG
```

Weitere Hinweise, insbesondere zu Startproblemen des gebauten Pakets: [BUILD.md](BUILD.md).

## Aufbau

```
core/                     Fachlogik, unabhängig von der Oberfläche
  io_fits.py              FITS laden, Header/WCS, Thumbnails
  alignment.py            Sternerkennung und Frame-Registrierung
  synthetic_tracking.py   Vektor-Gitter und Shift-and-Stack (CPU-Referenz)
  gpu_tracking.py         Gleiche Logik gebatcht über PyTorch
  detection.py            SNR-Peak-Suche und Duplikatreduktion
  astrometry.py           Gaia-Abgleich, WCS-Fit, Residuen
  mpc_report.py           MPC-80-Spalten-Format
  project.py              Sitzungen und Presets (SQLite)
gui/
  main_window.py          Menüs und Ablaufsteuerung
  workers.py              QThread-Wrapper um die core-Funktionen
  views/                  Viewer, Dialoge, Ergebnistabelle, Panels
tests/                    Unit-Tests mit synthetischen Aufnahmen
benchmarks/               CPU-vs-GPU-Messung (siehe RESULTS.md)
```

Rechenintensive Arbeit läuft grundsätzlich in Worker-Threads, damit die Oberfläche während
länger laufender Suchen bedienbar bleibt.

## GPU-Beschleunigung

Das Gerät wird automatisch gewählt: CUDA, sonst Apple MPS, sonst CPU. Ohne passende
Hardware läuft derselbe Code auf der CPU weiter.

Auf CPU-only-Hardware bringt der PyTorch-Pfad keinen Vorteil gegenüber der NumPy-Referenz —
der Gewinn entsteht erst durch echte Parallelität auf der GPU. Messwerte und Einordnung:
[benchmarks/RESULTS.md](benchmarks/RESULTS.md).

## Tests

```bash
.venv\Scripts\pytest
```

Die Tests erzeugen ihre FITS-Fixtures selbst; echte Teleskopdaten sind nicht nötig. Ein
automatisiertes GUI-Testing gibt es bewusst nicht flächendeckend, einzelne Widgets mit
fehleranfälliger Logik sind aber abgedeckt (etwa die Zuordnung von Bewertung zu Kandidat
beim Sortieren der Ergebnistabelle).

Unter Linux/CI ohne Display:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

## Lizenz

Noch nicht festgelegt. Bis eine `LICENSE`-Datei ergänzt ist, gelten die Standardregeln des
Urheberrechts — eine Weitergabe oder Nutzung durch Dritte ist damit formal nicht gestattet.
