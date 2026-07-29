from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clipped_stats
from astropy.time import Time
from scipy.ndimage import shift as ndi_shift

from core.alignment import RegisteredStack
from core.io_fits import FrameStack


@dataclass(frozen=True)
class VelocityVector:
    """Hypothetischer Bewegungsvektor eines Objekts (Synthetic-Tracking-Suchraum)."""

    speed_arcsec_per_min: float
    angle_deg: float  # 0° = +x-Achse (Spalten), math. positiv (gegen Uhrzeigersinn)


@dataclass
class StackResult:
    vector: VelocityVector
    image: np.ndarray
    peak_value: float
    peak_position: tuple[int, int]  # (row, col)
    snr: float
    #: Breite der durch Zero-Padding beeinträchtigten Randzone dieses Vektors. Nachgelagerte
    #: Auswertung (core.detection) muss dieselbe Zone ausschließen, sonst sind die SNR-Werte
    #: verschiedener Vektoren nicht vergleichbar.
    border_margin: int = 0


def build_velocity_grid(
    speed_range_arcsec_per_min: tuple[float, float],
    speed_step_arcsec_per_min: float,
    angle_step_deg: float,
) -> list[VelocityVector]:
    """Erzeugt ein Gitter hypothetischer Bewegungsvektoren über Geschwindigkeit × Winkel."""
    low, high = speed_range_arcsec_per_min
    speeds = np.arange(low, high + 1e-9, speed_step_arcsec_per_min)
    angles = np.arange(0.0, 360.0, angle_step_deg)
    return [
        VelocityVector(speed_arcsec_per_min=float(speed), angle_deg=float(angle))
        for speed in speeds
        for angle in angles
    ]


def frame_elapsed_minutes(obs_times: list[str], reference_index: int) -> np.ndarray:
    """Zeitdifferenz jedes Frames zum Referenzframe in Minuten, aus DATE-OBS-Headern."""
    times = Time(list(obs_times), format="fits", scale="utc")
    delta_days = (times - times[reference_index]).jd
    return np.asarray(delta_days, dtype=np.float64) * 24.0 * 60.0


def _vector_pixel_shift(
    vector: VelocityVector, elapsed_minutes: float, pixel_scale_arcsec: float
) -> tuple[float, float]:
    """(dx, dy) in Pixeln, um die sich ein Objekt mit `vector` seit dem Referenzframe bewegt hat."""
    speed_px_per_min = vector.speed_arcsec_per_min / pixel_scale_arcsec
    angle_rad = np.radians(vector.angle_deg)
    dx = speed_px_per_min * elapsed_minutes * np.cos(angle_rad)
    dy = speed_px_per_min * elapsed_minutes * np.sin(angle_rad)
    return dx, dy


def candidate_positions_per_frame(
    position: tuple[float, float],
    vector: VelocityVector,
    obs_times: list[str],
    reference_index: int,
    pixel_scale_arcsec: float,
) -> list[tuple[float, float]]:
    """Rechnet die (row, col)-Position eines Kandidaten für jeden Frame zurück (PLAN.md
    Abschnitt 4, Schritt 6). `position` ist die im Stack gefundene Position im Referenzframe.

    Bewusst *ohne* den Stern-Alignment-Anteil: dieser kompensiert nur die Teleskop-Drift
    zwischen den Aufnahmen. Die Positionen beziehen sich daher auf das sternfeld-feste
    Referenzraster — genau das Raster, auf das auch der Gaia-WCS-Fit passt, sodass die
    Ergebnisse direkt über die WCS in RA/Dec umgerechnet werden können."""
    elapsed = frame_elapsed_minutes(obs_times, reference_index)
    row, col = position

    positions = []
    for elapsed_minutes in elapsed:
        obj_dx, obj_dy = _vector_pixel_shift(vector, elapsed_minutes, pixel_scale_arcsec)
        positions.append((row + obj_dy, col + obj_dx))
    return positions


def per_frame_total_shifts(
    stack: FrameStack,
    registered: RegisteredStack,
    vector: VelocityVector,
    pixel_scale_arcsec: float,
) -> list[tuple[float, float]]:
    """Kombinierte (Stern-Alignment- + hypothetische Objektbewegungs-)Verschiebung (dx, dy)
    pro Frame, relativ zum Referenzframe."""
    reference_index = registered.reference_index
    obs_times = [frame.obs_time for frame in stack.frames]
    elapsed = frame_elapsed_minutes(obs_times, reference_index)

    shifts = []
    for index in range(len(stack.frames)):
        star_dx = registered[index].alignment.dx
        star_dy = registered[index].alignment.dy
        obj_dx, obj_dy = _vector_pixel_shift(vector, elapsed[index], pixel_scale_arcsec)
        shifts.append((star_dx + obj_dx, star_dy + obj_dy))
    return shifts


def shift_and_stack(
    stack: FrameStack,
    registered: RegisteredStack,
    vector: VelocityVector,
    pixel_scale_arcsec: float,
) -> np.ndarray:
    """Verschiebt jeden Frame um die kombinierte (Stern-Alignment- + hypothetische
    Objektbewegungs-)Verschiebung zurück auf das Referenzraster und summiert sie auf.
    Ein Objekt, das sich tatsächlich mit `vector` bewegt hat, addiert sich dadurch
    konstruktiv; alles andere (Sterne, Rauschen) verschmiert."""
    reference_index = registered.reference_index
    reference_shape = stack.frames[reference_index].data.shape
    accum = np.zeros(reference_shape, dtype=np.float64)

    shifts = per_frame_total_shifts(stack, registered, vector, pixel_scale_arcsec)
    for frame, (total_dx, total_dy) in zip(stack.frames, shifts, strict=True):
        # Ein Objekt an Referenzposition p erscheint in diesem Frame bei p + (dx, dy).
        # scipy.ndimage.shift(data, shift=(sr, sc)) liefert output[r, c] = input[r - sr, c - sc],
        # d.h. mit shift=(-dy, -dx) landet der Bildinhalt von p + (dx, dy) wieder bei p:
        # output[p] = input[p - (-(dx,dy))] = input[p + (dx, dy)].
        shifted = ndi_shift(
            frame.data.astype(np.float64),
            shift=(-total_dy, -total_dx),
            order=1,
            mode="constant",
            cval=0.0,
        )
        accum += shifted

    return accum


def required_border_margin(
    stack: FrameStack,
    registered: RegisteredStack,
    vector: VelocityVector,
    pixel_scale_arcsec: float,
) -> int:
    """Breite (in Pixeln) des Randbereichs, der für `vector` durch Zero-Padding beim
    Zurückschieben mindestens eines Frames beeinträchtigt sein kann und daher von
    Peak-Suche/Hintergrundstatistik ausgeschlossen werden muss."""
    shifts = per_frame_total_shifts(stack, registered, vector, pixel_scale_arcsec)
    max_abs_shift = max(max(abs(dx), abs(dy)) for dx, dy in shifts)
    return int(np.ceil(max_abs_shift)) + 1


def crop_valid_region(image: np.ndarray, margin: int) -> tuple[np.ndarray, int, int]:
    """Schneidet `margin` Pixel von jeder Seite ab (max. bis zur Bildmitte) und gibt den
    Ausschnitt zusammen mit dem (Zeilen-, Spalten-)Offset zur Rückrechnung in Bildkoordinaten
    zurück."""
    height, width = image.shape
    margin = max(0, min(margin, (height - 1) // 2, (width - 1) // 2))
    if margin == 0:
        return image, 0, 0
    return image[margin:-margin, margin:-margin], margin, margin


def build_stack_result(vector: VelocityVector, image: np.ndarray, margin: int) -> StackResult:
    """Bewertet ein bereits gestacktes Bild per Peak-SNR, wobei die durch Zero-Padding
    beeinträchtigte Randzone (Breite `margin`) von Hintergrundstatistik und Peak-Suche
    ausgeschlossen wird."""
    valid, row_offset, col_offset = crop_valid_region(image, margin)
    _, median, std = sigma_clipped_stats(valid, sigma=3.0)
    peak_index = np.unravel_index(np.argmax(valid), valid.shape)
    peak_value = float(valid[peak_index])
    snr = (peak_value - median) / std if std > 0 else 0.0
    return StackResult(
        vector=vector,
        image=image,
        peak_value=peak_value,
        peak_position=(int(peak_index[0] + row_offset), int(peak_index[1] + col_offset)),
        snr=float(snr),
        border_margin=margin,
    )


def evaluate_vector(
    stack: FrameStack,
    registered: RegisteredStack,
    vector: VelocityVector,
    pixel_scale_arcsec: float,
) -> StackResult:
    """Führt Shift-and-Stack für einen Vektor aus und bewertet das Ergebnis per Peak-SNR."""
    image = shift_and_stack(stack, registered, vector, pixel_scale_arcsec)
    margin = required_border_margin(stack, registered, vector, pixel_scale_arcsec)
    return build_stack_result(vector, image, margin)


def search_velocity_grid(
    stack: FrameStack,
    registered: RegisteredStack,
    grid: list[VelocityVector],
    pixel_scale_arcsec: float,
) -> list[StackResult]:
    """CPU-Referenzimplementierung: iteriert das Vektor-Gitter sequenziell.
    GPU-Batch-Verarbeitung des gesamten Gitters folgt in Phase 4."""
    return [evaluate_vector(stack, registered, vector, pixel_scale_arcsec) for vector in grid]
