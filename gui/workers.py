from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from core.alignment import RegisteredFrame, RegisteredStack, detect_stars, estimate_shift
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


class AlignmentWorker(QThread):
    """Erkennt Sterne pro Frame und registriert alle Frames auf einen Referenzframe."""

    progress = Signal(int, int)
    finished_alignment = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        stack: FrameStack,
        reference_index: int = 0,
        fwhm: float = 3.0,
        threshold_sigma: float = 5.0,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._stack = stack
        self._reference_index = reference_index
        self._fwhm = fwhm
        self._threshold_sigma = threshold_sigma

    def run(self) -> None:
        try:
            total = len(self._stack)
            star_lists = []
            for index, frame in enumerate(self._stack.frames, start=1):
                star_lists.append(
                    detect_stars(frame.data, fwhm=self._fwhm, threshold_sigma=self._threshold_sigma)
                )
                self.progress.emit(index, total)

            reference_stars = star_lists[self._reference_index]
            registered = [
                RegisteredFrame(
                    frame=frame, stars=stars, alignment=estimate_shift(reference_stars, stars)
                )
                for frame, stars in zip(self._stack.frames, star_lists, strict=True)
            ]
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_alignment.emit(
            RegisteredStack(reference_index=self._reference_index, frames=registered)
        )
