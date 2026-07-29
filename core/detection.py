from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clipped_stats
from photutils.detection import find_peaks

from core.synthetic_tracking import StackResult, VelocityVector, crop_valid_region

THUMBNAIL_SIZE = 32


@dataclass
class Candidate:
    """Ein einzelner SNR-Peak in einem gestackten Bild für einen bestimmten Vektor."""

    vector: VelocityVector
    position: tuple[int, int]  # (row, col) im Referenzframe
    snr: float
    peak_value: float
    image: np.ndarray  # volles Stack-Bild (Quelle für das Vorschaubild)


@dataclass
class DetectionResult:
    """Ein geclusterter Kandidat: mögliches Objekt, repräsentiert durch seinen stärksten Treffer
    über alle benachbarten Vektoren hinweg. `confirmed` wird vom Nutzer in der GUI gesetzt."""

    vector: VelocityVector
    position: tuple[int, int]
    snr: float
    peak_value: float
    thumbnail: np.ndarray
    confirmed: bool | None = None


def find_candidate_peaks(
    result: StackResult, snr_threshold: float = 5.0, box_size: int = 7
) -> list[Candidate]:
    """Findet alle lokalen SNR-Peaks oberhalb der Schwelle im gestackten Bild eines Vektors
    (nicht nur das globale Maximum) — in einem Frame können mehrere Objekte auftauchen.

    Die durch Zero-Padding beeinträchtigte Randzone des Vektors wird ausgeschlossen (wie in
    core.synthetic_tracking.build_stack_result). Sonst verzerren die Randpixel die
    Hintergrundstatistik unterschiedlich stark je nach Shift-Größe, und die SNR-Werte
    verschiedener Vektoren wären nicht mehr vergleichbar — langsame (falsche) Vektoren
    bekämen dadurch systematisch zu hohe Werte."""
    image = result.image
    valid, row_offset, col_offset = crop_valid_region(image, result.border_margin)
    _, median, std = sigma_clipped_stats(valid, sigma=3.0)
    if std <= 0:
        return []

    threshold = median + snr_threshold * std
    peaks = find_peaks(valid, threshold=threshold, box_size=box_size)
    if peaks is None or len(peaks) == 0:
        return []

    candidates = []
    for row in peaks:
        position = (int(row["y_peak"]) + row_offset, int(row["x_peak"]) + col_offset)
        peak_value = float(row["peak_value"])
        snr = (peak_value - median) / std
        candidates.append(
            Candidate(
                vector=result.vector,
                position=position,
                snr=float(snr),
                peak_value=peak_value,
                image=image,
            )
        )
    return candidates


def _extract_thumbnail(image: np.ndarray, position: tuple[int, int], size: int) -> np.ndarray:
    row, col = position
    half = size // 2
    height, width = image.shape
    row0, row1 = max(0, row - half), min(height, row + half)
    col0, col1 = max(0, col - half), min(width, col + half)
    return image[row0:row1, col0:col1]


def cluster_candidates(
    candidates: list[Candidate],
    position_tolerance: float = 3.0,
    thumbnail_size: int = THUMBNAIL_SIZE,
) -> list[DetectionResult]:
    """Reduziert Duplikate: ein echtes Objekt erzeugt Treffer in mehreren benachbarten
    Gitterzellen des Vektor-Gitters (PLAN.md Abschnitt 4, Schritt 5). Behält iterativ den
    jeweils stärksten verbliebenen Treffer und verwirft alle Treffer innerhalb von
    `position_tolerance` um ihn herum (Non-Maximum-Suppression).

    Bewusst *keine* transitive Nachbarschaft (Single-Linkage): bei dichten Kandidatenfeldern
    verkettet die sich über das gesamte Bild zu einem einzigen Cluster und lässt am Ende nur
    den global stärksten Peak übrig — echte, weit entfernte Objekte gingen dabei verloren.
    Non-Maximum-Suppression kann ein Objekt dagegen nur durch einen *nahen* stärkeren Treffer
    verdrängen. Lieber ein Duplikat zu viel in der Liste (der Nutzer verwirft es) als ein
    verlorenes Objekt."""
    if not candidates:
        return []

    order = sorted(range(len(candidates)), key=lambda i: -candidates[i].snr)
    positions = np.array([c.position for c in candidates], dtype=np.float64)
    suppressed = np.zeros(len(candidates), dtype=bool)

    results = []
    for index in order:
        if suppressed[index]:
            continue
        best = candidates[index]
        results.append(
            DetectionResult(
                vector=best.vector,
                position=best.position,
                snr=best.snr,
                peak_value=best.peak_value,
                thumbnail=_extract_thumbnail(best.image, best.position, thumbnail_size),
            )
        )
        distances = np.hypot(
            positions[:, 0] - positions[index, 0], positions[:, 1] - positions[index, 1]
        )
        suppressed |= distances <= position_tolerance

    return sorted(results, key=lambda r: -r.snr)


def detect_candidates(
    results: list[StackResult],
    snr_threshold: float = 5.0,
    position_tolerance: float = 3.0,
    thumbnail_size: int = THUMBNAIL_SIZE,
) -> list[DetectionResult]:
    """Führt Peak-Suche + Clustering über das gesamte Vektor-Gitter-Ergebnis aus und liefert
    die finale, nach SNR sortierte Kandidatenliste."""
    all_candidates: list[Candidate] = []
    for result in results:
        all_candidates.extend(find_candidate_peaks(result, snr_threshold=snr_threshold))
    return cluster_candidates(all_candidates, position_tolerance, thumbnail_size)
