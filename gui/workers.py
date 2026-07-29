from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from core.alignment import RegisteredFrame, RegisteredStack, StarList, detect_stars, estimate_shift
from core.astrometry import (
    build_approx_wcs,
    fit_astrometric_solution,
    match_stars_to_gaia,
    query_gaia_stars,
)
from core.detection import DetectionResult, detect_candidates
from core.gpu_tracking import search_velocity_grid_torch
from core.io_fits import FrameStack, find_fits_files, load_fits_frame
from core.synthetic_tracking import build_velocity_grid, search_velocity_grid


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


class DetectionWorker(QThread):
    """Durchsucht das Vektor-Gitter (CPU oder PyTorch-Batch) und gruppiert die SNR-Peaks zu
    einer Kandidatenliste."""

    status = Signal(str)
    progress = Signal(int, int)
    finished_detection = Signal(list)
    failed = Signal(str)

    #: Anzahl Vektoren pro Durchlauf. Die Gittersuche wird in Blöcken abgearbeitet, damit
    #: überhaupt Fortschritt gemeldet werden kann (die Suche kann Minuten dauern) und damit
    #: der GPU-Batch-Tensor (n_vektoren x n_frames x H x W) nicht beliebig groß wird.
    CHUNK_SIZE = 16

    def __init__(
        self,
        stack: FrameStack,
        registered: RegisteredStack,
        params: dict,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._stack = stack
        self._registered = registered
        self._params = params
        self._cancelled = False

    def cancel(self) -> None:
        """Bricht die Suche nach dem aktuellen Block ab."""
        self._cancelled = True

    def run(self) -> None:
        try:
            grid = build_velocity_grid(
                speed_range_arcsec_per_min=self._params["speed_range_arcsec_per_min"],
                speed_step_arcsec_per_min=self._params["speed_step_arcsec_per_min"],
                angle_step_deg=self._params["angle_step_deg"],
            )
            total = len(grid)
            self.status.emit(f"Durchsuche {total} Bewegungsvektoren ...")
            self.progress.emit(0, total)

            pixel_scale = self._params["pixel_scale_arcsec"]
            search = (
                search_velocity_grid_torch if self._params["use_gpu"] else search_velocity_grid
            )

            results = []
            for start in range(0, total, self.CHUNK_SIZE):
                if self._cancelled:
                    self.status.emit("Suche abgebrochen.")
                    self.finished_detection.emit([])
                    return
                chunk = grid[start : start + self.CHUNK_SIZE]
                results.extend(search(self._stack, self._registered, chunk, pixel_scale))
                self.progress.emit(min(start + self.CHUNK_SIZE, total), total)

            self.status.emit("Gruppiere Treffer ...")
            detections: list[DetectionResult] = detect_candidates(
                results, snr_threshold=self._params["snr_threshold"]
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_detection.emit(detections)


class AstrometryWorker(QThread):
    """Fragt Gaia nach Katalogsternen im Feld ab, matcht sie gegen erkannte Sterne im
    Referenzframe und fittet eine verfeinerte WCS-Lösung."""

    status = Signal(str)
    finished_astrometry = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        reference_stars: StarList,
        image_shape: tuple[int, int],
        params: dict,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._reference_stars = reference_stars
        self._image_shape = image_shape
        self._params = params

    def run(self) -> None:
        try:
            self.status.emit("Frage Gaia-Katalog ab ...")
            gaia_stars = query_gaia_stars(
                center_ra_deg=self._params["center_ra_deg"],
                center_dec_deg=self._params["center_dec_deg"],
                radius_deg=self._params["radius_deg"],
                mag_limit=self._params["mag_limit"],
            )
            if len(gaia_stars) == 0:
                self.failed.emit("Keine Gaia-Sterne im Suchradius gefunden.")
                return

            approx_wcs = build_approx_wcs(
                self._params["center_ra_deg"],
                self._params["center_dec_deg"],
                self._params["pixel_scale_arcsec"],
                self._image_shape,
            )

            self.status.emit("Matche erkannte Sterne gegen Gaia ...")
            matches = match_stars_to_gaia(
                self._reference_stars.x,
                self._reference_stars.y,
                approx_wcs,
                gaia_stars,
                max_separation_arcsec=self._params["max_separation_arcsec"],
            )
            if len(matches) < 3:
                self.failed.emit(
                    f"Nur {len(matches)} Gaia-Matches gefunden, mindestens 3 für WCS-Fit nötig."
                )
                return

            self.status.emit("Fitte WCS-Lösung ...")
            solution = fit_astrometric_solution(matches)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_astrometry.emit(solution)
