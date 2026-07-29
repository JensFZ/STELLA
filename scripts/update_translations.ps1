# Aktualisiert die Übersetzungsdateien.
#
# Ablauf:
#   1. lupdate durchsucht den Quelltext nach übersetzbaren Zeichenketten und traegt neue
#      in die .ts-Dateien ein (bestehende Übersetzungen bleiben erhalten).
#   2. lrelease kompiliert jede .ts zu einer .qm, die das Programm zur Laufzeit laedt.
#
# Nach dem Lauf die .ts-Dateien uebersetzen (z.B. mit pyside6-linguist) und das Skript
# erneut ausfuehren, damit die .qm-Dateien aktuell sind.
#
# Neue Sprache hinzufuegen:
#   1. Kuerzel in $Languages unten ergaenzen
#   2. Kuerzel in core/i18n.py bei SUPPORTED_LANGUAGES ergaenzen
#   3. Dieses Skript ausfuehren, danach i18n/stella_<kuerzel>.ts uebersetzen

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Deutsch ist die Quellsprache und braucht daher keine Uebersetzungsdatei.
$Languages = @("en")

$sources = @("main.py") + (Get-ChildItem gui -Recurse -Filter *.py | ForEach-Object { $_.FullName })
Write-Output "$($sources.Count) Quelldateien"

foreach ($lang in $Languages) {
    $ts = "i18n\stella_$lang.ts"
    $qm = "i18n\stella_$lang.qm"

    Write-Output "`n== $lang =="
    & ".\.venv\Scripts\pyside6-lupdate.exe" @sources -ts $ts
    & ".\.venv\Scripts\pyside6-lrelease.exe" $ts -qm $qm
}

Write-Output "`nFertig. Unuebersetzte Eintraege finden:"
Write-Output "  Select-String -Path i18n\*.ts -Pattern 'type=\""unfinished\""'"
