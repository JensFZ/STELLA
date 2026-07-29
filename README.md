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
- **Viewer** mit Zoom, Stretch, Thumbnail-Leiste und Frame-Blink
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

### Fertiges Paket (Windows)

Unter [Releases](https://github.com/JensFZ/STELLA/releases) liegt ein ZIP mit
`STELLA.exe`. Entpacken, starten — eine Python-Installation ist nicht nötig. Das Paket
enthält PyTorch in der CPU-Variante; für GPU-Beschleunigung siehe [BUILD.md](BUILD.md).

### Aus dem Quellcode

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

1. **Datei → FITS-Ordner öffnen** (`Strg+O`) liest zunächst nur die Header. Enthält der
   Ordner mehrere Aufnahmeserien, erscheint eine Auswahl mit Beginn, Dauer und Frame-Zahl
   je Serie; vorausgewählt ist die längste. Erst nach der Auswahl werden die Bilddaten
   geladen. Erwartet werden bereits kalibrierte Aufnahmen (Darks/Flats abgezogen) mit
   `DATE-OBS` im Header — die Zeitstempel sind für die Bewegungsrechnung zwingend.
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

## Umgang mit echten Aufnahmeordnern

Aufnahmeordner enthalten in der Praxis selten genau das, was sich stapeln lässt. STELLA
liest deshalb zuerst nur die Header (bei 2000 Dateien wenige Sekunden) und trifft daraus
eine Auswahl. Was dabei aussortiert wird, steht im Log.

- **Farbaufnahmen werden zu Mono gemittelt.** Entbayerte Frames liegen als drei Ebenen vor;
  für die Detektion ist die Farbe ohne Nutzen, das Mitteln verbessert sogar das Rauschen.
- **Rohaufnahmen von Farbsensoren werden entmosaikt.** Enthält der Header `BAYERPAT`, liegt
  das Sensormosaik noch in den Daten — als Schachbrettmuster sichtbar. STELLA mittelt dann
  je 2×2-Block zu einem Pixel. Beim Laden lässt sich das abschalten, siehe unten.
- **Nur eine Bildgröße.** Shift-and-Stack summiert alle Frames auf ein gemeinsames Raster.
  Liegen mehrere Größen im Ordner (Rohframes neben registrierten oder gestackten
  Ergebnissen), wird die häufigste verwendet, der Rest übersprungen.
- **Nur eine Aufnahmeserie.** Frames werden anhand ihrer Zeitstempel in Serien getrennt
  (Lücke > 10 min). Bei mehreren Serien fragt STELLA nach, welche verwendet werden soll —
  vorausgewählt ist die längste. Das ist wesentlich: Frames aus verschiedenen Nächten
  gemeinsam zu stapeln liefert Unsinn, weil das Teleskop anders ausgerichtet war und ein
  bewegtes Objekt das Bildfeld längst verlassen hätte.
- **Speicherbudget (2 GB).** Ein Ordner kann tausende Frames enthalten, die zusammen nicht
  in den Arbeitsspeicher passen — 2000 Frames à 1920×1080 wären als float32 rund 36 GB.
  Geladen wird der Anfang der Serie, soweit das Budget reicht.

Für Synthetic Tracking ist das auch fachlich richtig: gebraucht wird ein zeitlich
zusammenhängender Ausschnitt einer Nacht, keine Sammlung über Monate.

### Bayer-Muster (Rohaufnahmen von Farbkameras)

Rohframes einer Farbkamera enthalten das Sensormosaik: benachbarte Pixel messen
verschiedene Farben und damit verschiedene Helligkeiten. Das ist als Schachbrett sichtbar
und stört die Detektion erheblich, denn das Muster geht in die Hintergrundstatistik ein und
hebt die SNR-Schwelle — lichtschwache Objekte fallen darunter.

STELLA erkennt das an `BAYERPAT` und mittelt je 2×2-Block. An Aufnahmen eines Seestar S50
gemessen:

| | ohne Mittelung | mit Mittelung |
|---|---|---|
| Hintergrundrauschen | 133,1 | 90,9 |
| erkannte Sterne je Frame | 6 | 25 |

Die vierfache Sternausbeute ist der eigentliche Gewinn: darunter leidet sonst das Alignment.

**Preis:** die Auflösung halbiert sich (1920×1080 → 960×540) und der Pixelmaßstab
verdoppelt sich. Diesen berechnet STELLA aus `XPIXSZ` und `FOCALLEN` und trägt ihn in den
Suchdialog ein — Rohframes enthalten meist kein WCS, sonst gäbe es keinen Anhaltspunkt.

Abschalten lässt sich die Mittelung im Auswahldialog beim Laden; die Einstellung wird
gemerkt. Ohne sie bleibt die volle Auflösung erhalten, das Muster aber ebenfalls.

### Darstellung im Viewer

Die beiden Regler über dem Bild setzen Schwarz- und Weißpunkt als Vielfache des
Hintergrundrauschens σ, nicht als Perzentile. Der Unterschied ist erheblich: in einer
Astroaufnahme sind über 99 % der Pixel Hintergrund, ein 1 %–99,5 %-Stretch legt beide
Grenzen also mitten ins Rauschen. Er spannt dann rund 4 σ über die gesamte Graustufenskala,
und der Himmel erscheint als Fernsehschnee statt als schwarze Fläche.

Voreingestellt sind −1 σ und +20 σ. Ist ein Ziel zu schwach, den Weißpunkt senken — das holt
Schwaches hervor, lässt aber das Rauschen mitkommen.

Das betrifft ausschließlich die Anzeige. Die Detektion rechnet auf den Rohwerten mit eigener
Statistik; kein Reglerwert verändert ein Ergebnis.

Ein Beispiel aus dem Log:

```
2115 FITS-Dateien im Ordner
  Bildgröße (1920, 1080): 1594 Datei(en)
  Bildgröße (2048, 1271): 519 Datei(en)
521 Datei(en) mit abweichender Bildgröße übersprungen; verwende (1920, 1080)
4 getrennte Aufnahmeserien erkannt:
  Serie 1: 1164 Frames, 2025-02-16T23:01 bis 2025-02-17T01:29 (148 min)
Nur die längste Serie wird verwendet (1164 Frames ab 2025-02-16T23:01)
906 weitere Frame(s) dieser Serie wegen des Speicherbudgets (2.0 GB) nicht geladen
Lade 258 Frames der Größe (1920, 1080) (~2.0 GB)
```

## Fensteraufteilung

Das Bild ist der Hauptinhalt und bekommt den Platz. Die Aufteilung passt sich an:

- **Bei Hochformataufnahmen** (etwa 1080×1920 vom Seestar S50) wandert der Thumbnail-Streifen
  an die rechte Seite. Unter dem Bild würde er genau die Höhe wegnehmen, die das Hochformat
  braucht, während links und rechts Fläche frei bliebe.
- **Bild und Streifen** sind durch einen Ziehgriff getrennt, der Streifen lässt sich ganz
  zuklappen.
- **Kandidaten- und Astrometrie-Panel** lassen sich frei verschieben, andocken und über das
  Menü *Ansicht* ein- und ausblenden.

Fenstergröße und Anordnung werden beim Beenden gespeichert und beim nächsten Start
wiederhergestellt. *Ansicht → Anordnung zurücksetzen* stellt den Auslieferungszustand her.

## Sprache

Die Oberfläche gibt es auf Deutsch und Englisch, umschaltbar im Menü *Sprache*. Ohne
Einstellung folgt STELLA der Systemsprache. Die Umschaltung wirkt beim nächsten Start.

Zum Testen lässt sich die Sprache erzwingen:

```bash
set STELLA_LANGUAGE=en
```

Weitere Sprachen sind vorgesehen; wie sie hinzugefügt werden, steht in
[i18n/README.md](i18n/README.md).

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
