# Übersetzungen

STELLA nutzt den Übersetzungsmechanismus von Qt. Die Oberflächentexte stehen im Quelltext
in Zeichenketten, die zur Laufzeit gegen eine Übersetzungstabelle ersetzt werden.

## Quellsprache ist Deutsch

Die Texte im Quelltext sind deutsch; Deutsch braucht daher **keine** Übersetzungsdatei —
findet Qt keine Übersetzung, gibt es den Originaltext aus.

Das ist bewusst so: die Anwendung ist durchgängig deutsch kommentiert und entstand deutsch.
Qt unterstützt jede Quellsprache. Der Preis: eine weitere Sprache wird aus dem Deutschen
übersetzt, nicht aus dem Englischen. Wer das umdrehen möchte, müsste alle Zeichenketten im
Quelltext auf Englisch umstellen und eine `stella_de.ts` anlegen — machbar, aber eine
umfangreiche und riskante Änderung, die für sich stehen sollte.

## Dateien

| Datei | Bedeutung |
|---|---|
| `stella_<sprache>.ts` | Übersetzungsquelle (XML, gehört ins Repository) |
| `stella_<sprache>.qm` | kompilierte Fassung, die das Programm lädt |

## Übersetzung aktualisieren

Nach Änderungen an Oberflächentexten:

```bash
powershell -ExecutionPolicy Bypass -File scripts\update_translations.ps1
```

Das Skript sucht neue Texte im Quelltext, trägt sie in die `.ts`-Dateien ein (bestehende
Übersetzungen bleiben erhalten) und kompiliert die `.qm`-Dateien.

Danach die noch offenen Einträge übersetzen — komfortabel mit dem Qt Linguist:

```bash
.venv\Scripts\pyside6-linguist i18n\stella_en.ts
```

Anschließend das Skript erneut ausführen, damit die `.qm`-Datei die Ergänzungen enthält.
Offene Einträge finden:

```bash
Select-String -Path i18n\*.ts -Pattern 'type="unfinished"'
```

## Neue Sprache hinzufügen

Am Beispiel Französisch (`fr`):

1. In [`core/i18n.py`](../core/i18n.py) bei `SUPPORTED_LANGUAGES` ergänzen:
   `"fr": "Français"` — die Bezeichnung in der Sprache selbst, damit sie auch findet, wer
   die aktuelle Oberflächensprache nicht liest.
2. In [`scripts/update_translations.ps1`](../scripts/update_translations.ps1) das Kürzel bei
   `$Languages` ergänzen.
3. In [`stella.spec`](../stella.spec) die neue `.qm` bei `datas` ergänzen, sonst fehlt sie
   im gebauten Paket.
4. Skript ausführen, `i18n/stella_fr.ts` übersetzen, Skript erneut ausführen.

Der Test `test_every_supported_language_except_source_has_a_compiled_file` schlägt fehl,
solange Schritt 4 aussteht — eine im Menü angebotene Sprache ohne `.qm` würde sonst
kommentarlos die Quellsprache anzeigen.

## Sprache zur Laufzeit wählen

Reihenfolge, in der die Sprache bestimmt wird:

1. Umgebungsvariable `STELLA_LANGUAGE` (praktisch zum Testen: `STELLA_LANGUAGE=en`)
2. gespeicherte Einstellung aus dem Menü *Sprache*
3. Systemsprache
4. Quellsprache (Deutsch)

Ein Wechsel im Menü wirkt beim nächsten Start. Ein Wechsel im laufenden Programm würde
erfordern, dass jedes Fenster seine Beschriftungen neu setzt; ein halb übersetzter Zustand
wäre das wahrscheinlichere Ergebnis.

## Fallstricke

- **Keine eigene Wrapper-Funktion um `tr()` bauen.** `lupdate` wertet den Quelltext
  statisch aus und erkennt nur die bekannten Aufrufformen (`self.tr(...)`,
  `QCoreApplication.translate("Kontext", ...)`). Hinter einem Wrapper versteckte Texte
  landen gar nicht erst in der `.ts` — sie bleiben dann stillschweigend unübersetzt.
- **Keine übersetzten Texte auf Modulebene.** Konstanten werden beim Import ausgewertet,
  also bevor die Übersetzung installiert ist. Deshalb liefern etwa `column_labels()` und
  `status_label()` ihre Texte als Funktion.
- **Zustände nicht aus angezeigtem Text ableiten.** Übersetzter Text ändert sich mit der
  Sprache; die Bewertung der Kandidaten wird daher als Wert in einer eigenen Datenrolle
  geführt, nicht aus der Beschriftung zurückgelesen.
- **Platzhalter benennen** (`{count}` statt `{}`): so kann eine Übersetzung die Reihenfolge
  ändern, was in manchen Sprachen nötig ist.
- **Logmeldungen werden nicht übersetzt.** Sie dienen der Fehlersuche und sollen
  unabhängig von der eingestellten Sprache vergleichbar bleiben.
