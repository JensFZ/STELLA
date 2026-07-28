from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from core.io_fits import FrameStack, find_fits_files, load_fits_frame


class FrameStackLoader(QThread):
    """Lädt einen FITS-Ordner in einem Worker-Thread, damit die GUI responsiv bleibt."""

    progress = Signal(int, int)
    finished_loading = Signal(object)
    failed = Signal(str)

    def __init__(self, folder: Path, parent: QObject | None = None):
        super().__init__(parent)
        self._folder = Path(folder)

    def run(self) -> None:
        try:
            paths = find_fits_files(self._folder)
            total = len(paths)
            frames = []
            for index, path in enumerate(paths, start=1):
                frames.append(load_fits_frame(path))
                self.progress.emit(index, total)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_loading.emit(FrameStack(frames=frames))
