# Entwicklungsplan: Open-Source Synthetic-Tracking-Tool (Tycho-Tracker-Alternative)

> Dieses Dokument ist als Arbeitsauftrag für Claude Code gedacht. Es beschreibt Ziel, Architektur,
> Tech-Stack-Entscheidung und ein phasenweises Vorgehen. Claude Code soll dieses Dokument als
> `PLAN.md` im Projekt-Root ablegen und iterativ abarbeiten.

## 1. Zielsetzung

Ein Desktop-Tool mit grafischer Oberfläche, das faint/fast-moving Asteroiden in Serien von
Astro-Aufnahmen mittels **Synthetic Tracking** (Shift-and-Stack über hypothetische
Bewegungsvektoren, GPU-beschleunigt) detektiert und die Treffer gegen den **Gaia-Katalog**
astrometrisch vermisst. Kein CLI-only-Tool — die GUI ist Pflichtbestandteil ab MVP.

**Nicht-Ziele (v1):** keine Teleskopsteuerung, keine Live-Capture, kein Ersatz für
Bildkalibrierung (Darks/Flats werden als bereits kalibrierte FITS vorausgesetzt, Kalibrierung
kann später ergänzt werden).

## 2. Tech-Stack-Entscheidung

| Bereich | Wahl | Begründung |
|---|---|---|
| Sprache/Runtime | Python 3.11+ | Astronomie-Ökosystem (astropy, astroquery, photutils) ist hier konkurrenzlos; GPU-Libraries (CuPy/PyTorch) verfügbar |
| GUI-Framework | **PySide6 (Qt)** | Nativ, performant, gute Widget-Bibliothek für Tabellen/Viewer/Progress, läuft ohne Modifikation auf Windows/Linux/macOS |
| GPU-Beschleunigung | CuPy (NVIDIA/CUDA) mit NumPy-Fallback, optional PyTorch als Alternative wegen besserer Apple-Silicon (MPS)-Unterstützung | Tycho Tracker wirbt explizit mit AMD/NVIDIA/Apple-Silicon-Support — CuPy deckt nur NVIDIA gut ab, PyTorch deckt CUDA + MPS + notfalls CPU ab. **Empfehlung: PyTorch als primäres Backend**, da es die Multiplatform-GPU-Anforderung am ehesten erfüllt |
| FITS-Handling | astropy.io.fits | Standard |
| Source-Detection | photutils (DAOStarFinder / segmentation) | Etabliert, gut dokumentiert |
| Astrometrie/Katalog | astroquery (Gaia TAP-Abfrage), astropy.wcs | Für Plate-Solving ggf. Anbindung an lokale astrometry.net-Installation (optional, extern) |
| Packaging | PyInstaller (pro Plattform separat gebaut) | Einfachster Weg zu distributionsfähigen Binaries ohne Python-Installation beim Endnutzer |
| Persistenz | SQLite (Sitzungen/Projekte), JSON (Settings) | Keine externen Abhängigkeiten |

**Alternative, die verworfen wurde:** C#/.NET mit Avalonia UI (passt zu deinem beruflichen
Hintergrund, ist aber im Astro-Ökosystem deutlich dünner besiedelt — kein photutils/astroquery-
Äquivalent, Gaia-Anbindung und Plate-Solving müsstest du selbst bauen). Falls du lieber in .NET
bleiben willst, ist das eine Option, aber der Aufwand für Astro-Grundfunktionalität steigt
erheblich. Für dieses Projekt wird Python empfohlen.

## 3. Architektur (Module)

```
synthetic-tracker/
├── core/
│   ├── io_fits.py          # FITS laden, Header/WCS parsen, Bildstapel-Objekt
│   ├── alignment.py        # Sternfeld-Registrierung (Referenzframe-Alignment)
│   ├── synthetic_tracking.py  # Shift-and-stack über Geschwindigkeits-/Winkel-Gitter, GPU-Kernel
│   ├── detection.py        # Peak-/SNR-Detektion in gestackten Ergebnissen
│   ├── astrometry.py       # WCS-Fit, Gaia-Abgleich, Residuen-Berechnung
│   └── project.py          # Session-/Projektverwaltung (SQLite)
├── gui/
│   ├── main_window.py
│   ├── views/
│   │   ├── image_viewer.py       # FITS-Viewer mit Zoom/Stretch/Blink
│   │   ├── search_setup.py       # Parameter für Geschwindigkeits-/Winkelgitter, GPU-Auswahl
│   │   ├── results_table.py      # Kandidatenliste, sortierbar, mit Vorschau
│   │   └── progress_panel.py     # Fortschritt für lang laufende GPU-Jobs
│   └── workers.py          # QThread/QRunnable-Wrapper um core/-Funktionen (GUI darf nie blockieren)
├── tests/
└── PLAN.md
```

**Wichtiges Architekturprinzip:** GUI-Layer ruft niemals direkt rechenintensive `core`-Funktionen
im Main-Thread auf. Alles läuft über Worker-Threads mit Progress-Signalen, damit die Oberfläche
während GPU-Läufen (Minuten bis Stunden möglich) responsiv bleibt.

## 4. Kernalgorithmus: Synthetic Tracking (Kurzbeschreibung für Claude Code)

1. N kalibrierte Frames mit bekannten Zeitstempeln laden, auf Referenzframe ausrichten (Stern-Alignment).
2. Ein Gitter aus hypothetischen Bewegungsvektoren (Geschwindigkeit in arcsec/min × Richtungswinkel)
   definieren — Suchraum ist typischerweise durch erwartete NEO-Geschwindigkeiten begrenzt.
3. Für jeden Vektor: Frames entlang dieses Vektors zueinander verschieben und aufsummieren (Stack).
4. Im resultierenden Summenbild nach Punkten mit signifikant erhöhtem SNR gegenüber Hintergrundrauschen suchen.
5. Treffer über mehrere benachbarte Vektoren hinweg clustern (ein echtes Objekt erzeugt Treffer in
   mehreren nahen Gitterzellen), Duplikate reduzieren.
6. Für jeden Kandidaten: Position pro Frame zurückrechnen, WCS-Fit mit Gaia-Sternen verfeinern,
   RA/Dec + Restfehler ausgeben (Ziel: Sub-Arcsekunden-Genauigkeit wie beim Original).

Dieser Schritt (3+4) ist der GPU-kritische Pfad — hier lohnt sich Batch-Verarbeitung des ganzen
Vektor-Gitters auf der GPU statt Python-Schleife.

## 5. Phasenplan

### Phase 0 – Projekt-Setup
- Repo-Struktur, `pyproject.toml`/`requirements.txt`, venv, Basis-CI (lint + pytest)
- Leeres PySide6-Hauptfenster mit Menüleiste (Datei/Projekt/Hilfe) — bewusst zuerst die GUI-Hülle,
  damit "kein CLI-Tool" von Anfang an eingehalten wird

### Phase 1 – FITS-Import & Viewer (MVP-Baustein 1)
- FITS-Ordner laden, Header/WCS auslesen, Thumbnails generieren
- Bild-Viewer mit Zoom, Histogram-Stretch, Frame-für-Frame-Blink

### Phase 2 – Alignment
- Sternfeld-Erkennung (photutils) + Registrierung mehrerer Frames auf Referenzframe
- Visuelle Kontrolle im Viewer (Overlay erkannter Sterne)

### Phase 3 – Synthetic Tracking Core (CPU-Referenzimplementierung zuerst)
- Vektor-Gitter-Definition, Shift-and-Stack in NumPy, Korrektheit an Testdaten verifizieren
  (synthetische Testbilder mit bekanntem eingebettetem "Asteroiden"-Trail erzeugen für automatisierte Tests)

### Phase 4 – GPU-Beschleunigung
- Gleiche Logik mit PyTorch-Tensoren (CUDA/MPS), Fallback auf CPU-Pfad wenn keine GPU verfügbar
- Benchmark CPU vs. GPU dokumentieren

### Phase 5 – Detektion & Ergebnis-UI
- SNR-Peak-Suche, Clustering, Kandidatenliste in der GUI mit Vorschaubild pro Treffer
- Manuelle Bestätigung/Verwerfung durch Nutzer (wichtig — false positives sind bei dieser Technik normal)

### Phase 6 – Astrometrie
- Gaia-Abfrage via astroquery, WCS-Verfeinerung, Residuen-Anzeige
- Export im MPC-Report-Format (80-Spalten-Format bzw. ADES), damit Ergebnisse einreichbar sind

### Phase 7 – Projektverwaltung & Persistenz
- Sitzungen speichern/laden (SQLite), Parameter-Presets

### Phase 8 – Packaging
- PyInstaller-Build für die Entwicklungsplattform zuerst, Multiplatform-Builds optional/später
- Kein Muss laut Vorgabe — als eigener, klar abtrennbarer Schritt am Ende einplanen

## 6. Teststrategie
- Unit-Tests für `core/` mit synthetischen FITS-Testframes (kein Bedarf an echten Teleskopdaten)
- Kein automatisiertes GUI-Testing in v1 vorgesehen (Aufwand/Nutzen), stattdessen manuelle Checkliste pro Phase

## 7. Offene Entscheidungen für dich
- CUDA-fähige GPU vorhanden, oder eher Apple-Silicon-Mac? Das beeinflusst, ob PyTorch/MPS-Pfad
  von Anfang an priorisiert werden sollte.
- Reicht dir eine Single-Platform-Distribution (die, auf der du entwickelst), oder ist
  Multiplatform-Packaging von Anfang an relevant?

## 8. Hinweis zur Umsetzung mit Claude Code
- Dieses Dokument 1:1 als `PLAN.md` ins Repo legen, dann pro Phase einen eigenen Prompt/eine
  eigene Session starten ("Setze Phase 3 aus PLAN.md um") statt alles in einem Rutsch zu verlangen.
- Nach jeder Phase: kurzer manueller Test durch dich, bevor die nächste Phase beauftragt wird.
