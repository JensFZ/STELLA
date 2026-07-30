from __future__ import annotations

import logging
import time
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
from core.io_fits import (
    DEFAULT_MEMORY_BUDGET_BYTES,
    FolderScan,
    FrameStack,
    group_into_sessions,
    load_fits_frame,
    scan_folder,
    select_frames_to_load,
)
from core.synthetic_tracking import build_velocity_grid, search_velocity_grid

logger = logging.getLogger(__name__)


class FolderScanWorker(QThread):
    """Liest die Header eines FITS-Ordners.

    Bewusst als eigener Schritt vor dem Laden: nur so lässt sich dem Nutzer die
    Serienauswahl anbieten, bevor Gigabytes an Bilddaten gelesen werden. Der Scan selbst
    ist vergleichsweise schnell (rund 2000 Dateien in wenigen Sekunden), blockiert die
    Oberfläche aber trotzdem spürbar — daher im Worker-Thread.
    """

    finished_scan = Signal(object)
    failed = Signal(str)

    def __init__(self, folder: Path, *, debayer: bool = True, parent: QObject | None = None):
        super().__init__(parent)
        self._folder = Path(folder)
        self._debayer = debayer

    def run(self) -> None:
        started = time.perf_counter()
        logger.info("Analysiere FITS-Ordner %s", self._folder)
        try:
            scan = scan_folder(self._folder, debayer=self._debayer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ordneranalyse fehlgeschlagen")
            self.failed.emit(str(exc))
            return

        logger.info(
            "%d FITS-Dateien in %.1fs analysiert", len(scan.infos), time.perf_counter() - started
        )
        for shape, count in scan.shape_groups():
            logger.info("  Bildgröße %s: %d Datei(en)", shape, count)
        for path, error in scan.unreadable[:5]:
            logger.warning("  nicht lesbar: %s (%s)", path.name, error)

        patterns = scan.bayer_patterns()
        if patterns:
            logger.info(
                "Bayer-Muster erkannt: %s — 2×2-Mittelung %s",
                ", ".join(sorted(patterns)),
                "aktiv" if self._debayer else "abgeschaltet",
            )
            if not self._debayer:
                # Ohne Mittelung bleibt das Mosaik in den Daten und hebt die Nachweisgrenze.
                logger.warning(
                    "Ohne Bayer-Mittelung verbleibt das Sensormosaik in den Daten; es erhöht "
                    "das gemessene Hintergrundrauschen und damit die SNR-Schwelle."
                )
        scale = scan.pixel_scale_arcsec()
        if scale:
            logger.info("Pixelmaßstab laut Header: %.3f arcsec/px", scale)

        if not scan.infos:
            self.failed.emit(f"Keine lesbaren FITS-Dateien in {self._folder} gefunden.")
            return

        shape = scan.dominant_shape()
        skipped_other_shape = len(scan.infos) - len(scan.for_shape(shape))
        if skipped_other_shape:
            # Shift-and-Stack summiert alle Frames auf ein gemeinsames Raster —
            # abweichende Bildgrößen lassen sich nicht gemeinsam verarbeiten.
            logger.warning(
                "%d Datei(en) mit abweichender Bildgröße übersprungen; verwende %s",
                skipped_other_shape,
                shape,
            )

        sessions = group_into_sessions(scan.for_shape(shape))
        logger.info("%d Aufnahmeserie(n) erkannt:", len(sessions))
        for number, session in enumerate(sessions):
            logger.info(
                "  Serie %d: %d Frames, %s bis %s (%.0f min)",
                number,
                len(session),
                session.start,
                session.end,
                session.duration_minutes,
            )

        self.finished_scan.emit(scan)


class FrameStackLoader(QThread):
    """Lädt die Bilddaten der gewählten Aufnahmeserie in einem Worker-Thread.

    Erwartet einen bereits erstellten `FolderScan`, damit der Ordner nicht zweimal
    durchlaufen werden muss.
    """

    status = Signal(str)
    progress = Signal(int, int)
    finished_loading = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        scan: FolderScan,
        *,
        session_index: int | None = None,
        max_frames: int | None = None,
        memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
        debayer: bool = True,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._scan = scan
        self._session_index = session_index
        self._max_frames = max_frames
        self._memory_budget_bytes = memory_budget_bytes
        self._debayer = debayer

    def run(self) -> None:
        started = time.perf_counter()
        try:
            shape = self._scan.dominant_shape()
            sessions = group_into_sessions(self._scan.for_shape(shape))

            selected = select_frames_to_load(
                self._scan,
                shape=shape,
                session_index=self._session_index,
                max_frames=self._max_frames,
                memory_budget_bytes=self._memory_budget_bytes,
            )
            if not selected:
                self.failed.emit("Keine verwendbaren Frames im Ordner gefunden.")
                return

            chosen = (
                sessions[self._session_index]
                if self._session_index is not None
                else max(sessions, key=len)
            )
            logger.info(
                "Gewählte Serie: %d Frames, %s bis %s (%.0f min)",
                len(chosen),
                chosen.start,
                chosen.end,
                chosen.duration_minutes,
            )
            skipped_budget = len(chosen) - len(selected)
            if skipped_budget > 0:
                logger.warning(
                    "%d weitere Frame(s) dieser Serie wegen des Speicherbudgets (%.1f GB) "
                    "nicht geladen",
                    skipped_budget,
                    self._memory_budget_bytes / 1024**3,
                )

            total = len(selected)
            logger.info(
                "Lade %d Frames der Größe %s (~%.1f GB)",
                total,
                shape,
                total * selected[0].bytes_as_float32 / 1024**3,
            )
            self.status.emit(f"Lade {total} Frames ...")

            frames = []
            for index, info in enumerate(selected, start=1):
                frames.append(load_fits_frame(info.path, debayer=self._debayer))
                logger.debug("Frame %d/%d: %s", index, total, info.path.name)
                self.progress.emit(index, total)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Laden des FITS-Ordners fehlgeschlagen")
            self.failed.emit(str(exc))
            return

        without_time = [f.path.name for f in frames if not f.obs_time]
        if without_time:
            # Ohne DATE-OBS ist keine Bewegungsrechnung möglich; das fällt sonst erst
            # viel später bei der Suche auf.
            logger.warning(
                "%d Frame(s) ohne DATE-OBS im Header: %s",
                len(without_time),
                ", ".join(without_time[:5]),
            )

        logger.info("%d Frames geladen in %.1fs", len(frames), time.perf_counter() - started)
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
        started = time.perf_counter()
        logger.info(
            "Starte Alignment: %d Frames, Referenz %d, FWHM %.1f, Schwelle %.1f sigma",
            len(self._stack),
            self._reference_index,
            self._fwhm,
            self._threshold_sigma,
        )
        try:
            total = len(self._stack)
            star_lists = []
            for index, frame in enumerate(self._stack.frames, start=1):
                star_lists.append(
                    detect_stars(frame.data, fwhm=self._fwhm, threshold_sigma=self._threshold_sigma)
                )
                logger.debug(
                    "Frame %d/%d (%s): %d Sterne erkannt",
                    index,
                    total,
                    frame.path.name,
                    len(star_lists[-1]),
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
            logger.exception("Alignment fehlgeschlagen")
            self.failed.emit(str(exc))
            return

        for index, entry in enumerate(registered):
            alignment = entry.alignment
            # Wenige Matches deuten auf ein zu schwaches Sternfeld oder zu große Drift hin
            # — die Ursache, wenn die spätere Suche nichts findet.
            log = logger.warning if alignment.n_matches < 3 else logger.info
            log(
                "Frame %d (%s): dx=%+.2f dy=%+.2f, %d Sterne gematcht",
                index,
                entry.frame.path.name,
                alignment.dx,
                alignment.dy,
                alignment.n_matches,
            )

        logger.info("Alignment abgeschlossen in %.1fs", time.perf_counter() - started)
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
    #: überhaupt Fortschritt gemeldet werden kann (die Suche kann Minuten dauern). Der
    #: PyTorch-Pfad unterteilt zusätzlich selbst noch einmal nach Speicherbudget (siehe
    #: core.gpu_tracking._max_vectors_per_batch) — dieser Wert hier ist keine
    #: Speicherobergrenze, sondern reine Fortschritts-Granularität.
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
        started = time.perf_counter()
        logger.info("Starte Kandidatensuche mit Parametern: %s", self._params)
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
            logger.info(
                "%d Vektoren, %d Frames, Pfad: %s, Blockgröße %d",
                total,
                len(self._stack),
                "PyTorch-Batch" if self._params["use_gpu"] else "NumPy/SciPy (CPU)",
                self.CHUNK_SIZE,
            )

            results = []
            for start in range(0, total, self.CHUNK_SIZE):
                if self._cancelled:
                    logger.info(
                        "Suche vom Nutzer abgebrochen nach %d/%d Vektoren", len(results), total
                    )
                    self.status.emit("Suche abgebrochen.")
                    self.finished_detection.emit([])
                    return
                chunk_started = time.perf_counter()
                chunk = grid[start : start + self.CHUNK_SIZE]
                results.extend(search(self._stack, self._registered, chunk, pixel_scale))
                logger.debug(
                    "Block %d-%d von %d in %.2fs",
                    start,
                    min(start + self.CHUNK_SIZE, total),
                    total,
                    time.perf_counter() - chunk_started,
                )
                self.progress.emit(min(start + self.CHUNK_SIZE, total), total)

            search_seconds = time.perf_counter() - started
            logger.info(
                "Gittersuche fertig in %.1fs (%.2fs je Vektor)",
                search_seconds,
                search_seconds / max(total, 1),
            )

            self.status.emit("Gruppiere Treffer ...")
            detections: list[DetectionResult] = detect_candidates(
                results, snr_threshold=self._params["snr_threshold"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Kandidatensuche fehlgeschlagen")
            self.failed.emit(str(exc))
            return

        if detections:
            logger.info(
                "%d Kandidat(en) nach Gruppierung, stärkster: SNR %.1f bei %s mit %s",
                len(detections),
                detections[0].snr,
                detections[0].position,
                detections[0].vector,
            )
        else:
            # Häufigste Ursachen: Suchraum verfehlt die Objektgeschwindigkeit oder die
            # SNR-Schwelle ist zu hoch angesetzt.
            logger.warning(
                "Keine Kandidaten über der SNR-Schwelle %.1f gefunden",
                self._params["snr_threshold"],
            )
        logger.info("Kandidatensuche gesamt %.1fs", time.perf_counter() - started)
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
        started = time.perf_counter()
        logger.info("Starte Astrometrie mit Parametern: %s", self._params)
        try:
            self.status.emit("Frage Gaia-Katalog ab ...")
            query_started = time.perf_counter()
            gaia_stars = query_gaia_stars(
                center_ra_deg=self._params["center_ra_deg"],
                center_dec_deg=self._params["center_dec_deg"],
                radius_deg=self._params["radius_deg"],
                mag_limit=self._params["mag_limit"],
            )
            logger.info(
                "Gaia lieferte %d Sterne in %.1fs",
                len(gaia_stars),
                time.perf_counter() - query_started,
            )
            if len(gaia_stars) == 0:
                logger.warning("Gaia-Abfrage ohne Treffer — Feldzentrum oder Radius prüfen")
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
            logger.info(
                "%d von %d erkannten Sternen gematcht (Toleranz %.1f arcsec)",
                len(matches),
                len(self._reference_stars),
                self._params["max_separation_arcsec"],
            )
            if len(matches) < 3:
                # Typisch bei falschem Feldzentrum, falschem Pixelmaßstab oder zu enger
                # Toleranz — die Näherungs-WCS trifft dann daneben.
                logger.warning(
                    "Zu wenige Matches für einen WCS-Fit. Feldzentrum, Pixelmaßstab und "
                    "Match-Toleranz prüfen."
                )
                self.failed.emit(
                    f"Nur {len(matches)} Gaia-Matches gefunden, mindestens 3 für WCS-Fit nötig."
                )
                return

            self.status.emit("Fitte WCS-Lösung ...")
            solution = fit_astrometric_solution(matches)
        except Exception as exc:  # noqa: BLE001
            # Hier landen auch Netzwerkfehler der Gaia-Abfrage; der Traceback zeigt, ob es
            # an der Verbindung oder an den Daten lag.
            logger.exception("Astrometrie fehlgeschlagen")
            self.failed.emit(str(exc))
            return

        logger.info(
            "WCS-Fit: %d Matches, RMS %.3f arcsec, max %.3f arcsec (gesamt %.1fs)",
            solution.n_matches,
            solution.rms_residual_arcsec,
            float(solution.residuals_arcsec.max()),
            time.perf_counter() - started,
        )
        self.finished_astrometry.emit(solution)
