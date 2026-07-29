# Smoke-Test fuer den PyInstaller-Build.
#
# Prueft NICHT nur, ob der Prozess laeuft: bei console=False zeigt PyInstaller im
# Fehlerfall einen modalen Fehlerdialog, und der haelt den Prozess ebenfalls am Leben
# ("Responding=True"). Ein Test, der nur auf "Prozess lebt" schaut, meldet deshalb auch
# bei einem harten Importfehler faelschlich Erfolg.
#
# Zwei Betriebsarten:
#
#   (Standard)  Startet die Anwendung normal und prueft, ob das echte Qt-Hauptfenster mit
#               dem Titel "STELLA" erscheint. Bricht der Import ab, traegt das einzige
#               Fenster den Titel des PyInstaller-Fehlerdialogs -- der Test schlaegt dann
#               korrekt fehl. Bewusst OHNE QT_QPA_PLATFORM=offscreen: ohne echtes Fenster
#               gaebe es keinen Titel zum Pruefen.
#
#   -Headless   Startet die Anwendung mit --selftest und wertet den Rueckgabewert aus.
#               Fuer CI-Runner, auf denen keine sichtbare Fenstersitzung zur Verfuegung
#               steht. Der Selbsttest prueft zusaetzlich, ob die angeforderte
#               Uebersetzung wirklich geladen wurde, deckt also mehr ab als der
#               Fenstertitel. Ein haengender Fehlerdialog wird durch das Zeitlimit
#               abgefangen -- ohne das wartete der Lauf bis zum Job-Timeout.

param(
    [switch]$Headless,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\STELLA\STELLA.exe"

if (-not (Test-Path $exe)) {
    Write-Output "FEHLER: $exe nicht gefunden - wurde `pyinstaller stella.spec` ausgefuehrt?"
    exit 1
}

$size = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Output ("Bundle-Groesse: {0:N0} MB" -f $size)

if ($Headless) {
    # Eine nicht-deutsche Sprache anfordern: nur so faellt auf, wenn die kompilierte
    # .qm nicht im Bundle gelandet ist. Bei Deutsch greift ohnehin kein Translator.
    $env:STELLA_LANGUAGE = "en"
    $env:QT_QPA_PLATFORM = "offscreen"

    $proc = Start-Process -FilePath $exe -ArgumentList "--selftest" -PassThru
    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        Write-Output "FEHLER: Selbsttest nach ${TimeoutSeconds}s nicht beendet."
        Write-Output "        Deutet auf den modalen PyInstaller-Fehlerdialog hin."
        Stop-Process -Id $proc.Id -Force
        exit 1
    }
    if ($proc.ExitCode -ne 0) {
        Write-Output "FEHLER: Selbsttest fehlgeschlagen, ExitCode=$($proc.ExitCode)."
        Write-Output "        Grund steht in %USERPROFILE%\.stella\logs\stella.log"
        exit 1
    }
    Write-Output "OK: Selbsttest bestanden, Build ist startfaehig."
    exit 0
}

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
