## Installation

ZIP herunterladen, entpacken, `STELLA.exe` starten. Eine Python-Installation ist nicht
erforderlich. Der Ordner muss vollständig zusammenbleiben — die `.exe` allein läuft nicht.

Windows SmartScreen meldet sich beim ersten Start, weil das Paket nicht signiert ist:
*Weitere Informationen* → *Trotzdem ausführen*.

Die Prüfsumme der ZIP steht in der beiliegenden `.sha256`-Datei:

```powershell
Get-FileHash STELLA-*-windows-x64.zip -Algorithm SHA256
```

## Hinweise

- **Nur Windows x64.** PyInstaller kann nicht cross-kompilieren; für Linux und macOS muss
  dasselbe `stella.spec` auf der Zielplattform gebaut werden.
- **PyTorch ist CPU-only.** Die Gittersuche läuft ohne GPU-Beschleunigung. Wer CUDA nutzen
  möchte, baut selbst — siehe `BUILD.md`.
- **Der erste Start dauert länger**, weil astropy seinen Cache anlegt.
- **Die Gaia-Abfrage braucht Internet.** Import, Viewer, Alignment, Suche und Detektion
  laufen vollständig offline.
- Bei Problemen: `%USERPROFILE%\.stella\logs\stella.log`, erreichbar auch über
  *Hilfe → Logdatei anzeigen*.
