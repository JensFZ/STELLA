# Smoke-Test für den PyInstaller-Build.
#
# Prueft NICHT nur, ob der Prozess laeuft: bei console=False zeigt PyInstaller im
# Fehlerfall einen modalen Fehlerdialog, und der haelt den Prozess ebenfalls am Leben
# ("Responding=True"). Ein Test, der nur auf "Prozess lebt" schaut, meldet deshalb auch
# bei einem harten Importfehler faelschlich Erfolg.
#
# Stattdessen wird geprueft, ob das echte Qt-Hauptfenster mit dem Titel "STELLA"
# erscheint. Bricht der Import ab, traegt das einzige Fenster den Titel des
# PyInstaller-Fehlerdialogs — der Test schlaegt dann korrekt fehl.
#
# Bewusst OHNE QT_QPA_PLATFORM=offscreen: ohne echtes Fenster gaebe es keinen Fenstertitel
# zum Pruefen. Der Test blendet daher kurz ein Fenster ein.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\STELLA\STELLA.exe"

if (-not (Test-Path $exe)) {
    Write-Output "FEHLER: $exe nicht gefunden - wurde `pyinstaller stella.spec` ausgefuehrt?"
    exit 1
}

$size = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Output ("Bundle-Groesse: {0:N0} MB" -f $size)

$proc = Start-Process -FilePath $exe -PassThru

# Der erste Start dauert laenger (astropy legt seinen Cache an), daher bis zu 60s warten.
$title = ""
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
        Write-Output "FEHLER: Prozess sofort beendet, ExitCode=$($proc.ExitCode)"
        exit 1
    }
    $proc.Refresh()
    $title = $proc.MainWindowTitle
    if ($title) { break }
}

if (-not $title) {
    Write-Output "FEHLER: nach 60s kein Fenster erschienen"
    Stop-Process -Id $proc.Id -Force
    exit 1
}

Write-Output "Fenstertitel: '$title'"
Stop-Process -Id $proc.Id -Force

if ($title -ne "STELLA") {
    Write-Output "FEHLER: erwartet wurde das Hauptfenster 'STELLA'."
    Write-Output "        Ein abweichender Titel deutet auf den PyInstaller-Fehlerdialog hin,"
    Write-Output "        d.h. das Programm ist beim Starten abgebrochen."
    exit 1
}

Write-Output "OK: Hauptfenster ist erschienen, Build ist startfaehig."
