from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".stella" / "logs"
LOG_FILENAME = "stella.log"

#: Umgebungsvariable, mit der sich die Ausführlichkeit ohne Neubau ändern lässt,
#: z.B. `STELLA_LOG_LEVEL=DEBUG`.
LEVEL_ENV_VAR = "STELLA_LOG_LEVEL"

#: Eine Logdatei pro Lauf wäre unübersichtlich, eine unbegrenzte wächst ewig — daher
#: Rotation über wenige Dateien.
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def log_file_path(log_dir: Path | None = None) -> Path:
    return (log_dir or DEFAULT_LOG_DIR) / LOG_FILENAME


def configure_logging(level: int | str | None = None, log_dir: Path | None = None) -> Path:
    """Richtet Konsolen- und Datei-Logging ein und gibt den Pfad der Logdatei zurück.

    Die Datei ist der wichtigere der beiden Kanäle: das ausgelieferte Programm wird mit
    `console=False` gebaut (siehe stella.spec), dort gibt es keine sichtbare Konsole. Die
    Logdatei lässt sich dagegen bei einem Problem einfach mitschicken.
    """
    import os

    if level is None:
        level = os.environ.get(LEVEL_ENV_VAR, "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    directory = log_dir or DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_FILENAME

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)

    # Mehrfachaufrufe (z.B. in Tests) dürfen keine doppelten Handler anhängen.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # In einem mit console=False gebauten Programm ist sys.stderr None — ein StreamHandler
    # darauf würde beim ersten Logeintrag scheitern. Konsole daher nur anhängen, wenn es
    # wirklich eine gibt (Entwicklungsstart oder console=True-Build).
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    return path


def log_environment() -> None:
    """Schreibt einmalig die Eckdaten der Umgebung ins Log. Steht am Anfang jedes Laufs und
    beantwortet bei einer Fehlermeldung die ersten Rückfragen (Version, Gerät, gebaut oder
    aus dem Quellcode gestartet)."""
    logger = logging.getLogger("stella.environment")
    frozen = getattr(sys, "frozen", False)

    logger.info("STELLA startet (%s)", "gebautes Paket" if frozen else "aus dem Quellcode")
    logger.info("Python %s auf %s", sys.version.split()[0], platform.platform())

    for module_name in ("numpy", "astropy", "photutils", "scipy", "torch", "PySide6"):
        try:
            module = __import__(module_name)
            logger.info("  %-10s %s", module_name, getattr(module, "__version__", "unbekannt"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  %-10s nicht importierbar: %s", module_name, exc)

    try:
        from core.gpu_tracking import get_device

        logger.info("Rechengerät für die Gittersuche: %s", get_device())
    except Exception:  # noqa: BLE001
        logger.exception("Gerätewahl fehlgeschlagen")


def install_excepthook() -> None:
    """Leitet sonst unbehandelte Ausnahmen ins Log um.

    Ohne das verschwindet ein Absturz im gebauten Programm hinter dem PyInstaller-Dialog,
    dessen Text sich nicht kopieren lässt — im Log steht er anschließend vollständig.
    """
    logger = logging.getLogger("stella.excepthook")
    previous_hook = sys.excepthook

    def handle(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, KeyboardInterrupt):
            logger.critical(
                "Unbehandelte Ausnahme", exc_info=(exc_type, exc_value, exc_traceback)
            )
        previous_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle
