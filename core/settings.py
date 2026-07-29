from __future__ import annotations

from PySide6.QtCore import QSettings

#: Ablageort der Einstellungen. Unter Windows die Registry, sonst eine Konfigurationsdatei —
#: Qt wählt das plattformübliche Ziel selbst.
ORGANISATION = "STELLA"
APPLICATION = "STELLA"


def settings() -> QSettings:
    """Zugriff auf die dauerhaften Einstellungen (Sprache, Fensteranordnung).

    Bewusst eine gemeinsame Stelle statt verstreuter QSettings-Aufrufe: sonst genügt ein
    abweichender Organisations- oder Anwendungsname an einer Stelle, damit deren Werte in
    einem anderen Zweig landen und stillschweigend nie wieder gefunden werden.
    """
    return QSettings(ORGANISATION, APPLICATION)
