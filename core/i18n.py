from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from core.settings import settings

logger = logging.getLogger(__name__)

#: Sprache, in der die Zeichenketten im Quellcode stehen. Für sie gibt es keine
#: Übersetzungsdatei — Qt gibt den Originaltext aus, wenn kein Translator greift.
SOURCE_LANGUAGE = "de"

#: Angebotene Sprachen: Kürzel -> Bezeichnung in der jeweiligen Sprache selbst
#: (so findet sie auch jemand, der die aktuelle Oberflächensprache nicht versteht).
#: Eine weitere Sprache erfordert nur einen Eintrag hier und eine passende
#: i18n/stella_<kürzel>.ts — siehe i18n/README.md.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}

#: Umgebungsvariable, die die Sprachwahl überschreibt (praktisch zum Testen).
LANGUAGE_ENV_VAR = "STELLA_LANGUAGE"

_SETTINGS_KEY = "language"

#: Hält die installierten Translator am Leben. Qt entfernt einen Translator, sobald das
#: Python-Objekt eingesammelt wird — ohne diese Referenz wäre die Übersetzung sofort wieder weg.
_installed: list[QTranslator] = []

_current_language = SOURCE_LANGUAGE


def translations_directory() -> Path:
    """Verzeichnis mit den kompilierten .qm-Dateien.

    Im gebauten Paket liegen die Daten in dem von PyInstaller entpackten Verzeichnis
    (`sys._MEIPASS`), beim Start aus dem Quellcode im Projektordner.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "i18n"
    return Path(__file__).resolve().parent.parent / "i18n"


def saved_language() -> str | None:
    value = settings().value(_SETTINGS_KEY)
    return str(value) if value else None


def save_language(language: str) -> None:
    settings().setValue(_SETTINGS_KEY, language)


def current_language() -> str:
    return _current_language


def _system_language() -> str:
    """Sprachkürzel des Betriebssystems, z.B. „de“ aus „de_DE“.

    Eigene Funktion, damit Tests sie ersetzen können: sonst hinge ihr Ergebnis von der
    Spracheinstellung des ausführenden Rechners ab.
    """
    return QLocale.system().name().split("_")[0]


def resolve_language(explicit: str | None = None) -> str:
    """Ermittelt die zu verwendende Sprache.

    Reihenfolge: ausdrückliche Angabe, Umgebungsvariable, gespeicherte Einstellung,
    Systemsprache, Quellsprache. Nicht unterstützte Werte werden ignoriert.
    """
    candidates = [
        explicit,
        os.environ.get(LANGUAGE_ENV_VAR),
        saved_language(),
        _system_language(),
    ]
    for candidate in candidates:
        if candidate and candidate in SUPPORTED_LANGUAGES:
            return candidate
    return SOURCE_LANGUAGE


def install_translator(app: QCoreApplication, language: str | None = None) -> str:
    """Installiert die Übersetzung und gibt die tatsächlich verwendete Sprache zurück."""
    global _current_language

    for translator in _installed:
        app.removeTranslator(translator)
    _installed.clear()

    resolved = resolve_language(language)
    _current_language = resolved

    if resolved != SOURCE_LANGUAGE:
        path = translations_directory() / f"stella_{resolved}.qm"
        translator = QTranslator()
        if path.exists() and translator.load(str(path)):
            app.installTranslator(translator)
            _installed.append(translator)
            logger.info("Übersetzung geladen: %s", path)
        else:
            # Kein harter Fehler: die Oberfläche bleibt dann in der Quellsprache.
            logger.warning(
                "Übersetzungsdatei fehlt oder ist unlesbar: %s — Oberfläche bleibt auf %s",
                path,
                SOURCE_LANGUAGE,
            )
            _current_language = SOURCE_LANGUAGE

    _install_qt_translator(app, _current_language)
    return _current_language


def _install_qt_translator(app: QCoreApplication, language: str) -> None:
    """Übersetzt auch Qts eigene Standardtexte (Dateidialog, Standardschaltflächen).

    Ohne das erschiene etwa der Datei-Auswahldialog weiter in der Systemsprache, während
    der Rest der Oberfläche der Einstellung folgt.
    """
    translator = QTranslator()
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(f"qtbase_{language}", directory):
        app.installTranslator(translator)
        _installed.append(translator)
