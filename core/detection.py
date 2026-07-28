from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clipped_stats
from photutils.detection import find_peaks

from core.synthetic_tracking import StackResult, VelocityVector

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
    (nicht nur das globale Maximum) — in einem Frame können mehrere Objekte auftauchen."""
    image = result.image
    _, median, std = sigma_clipped_stats(image, sigma=3.0)
    if std <= 0:
        return []

    threshold = median + snr_threshold * std
    peaks = find_peaks(image, threshold=threshold, box_size=box_size)
    if peaks is None or len(peaks) == 0:
        return []

    candidates = []
    for row in peaks:
        position = (int(row["y_peak"]), int(row["x_peak"]))
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
    """Fasst Kandidaten zusammen, die auf dasselbe Objekt treffen: ein echtes Objekt erzeugt
    Peaks in mehreren benachbarten Gitterzellen des Vektor-Gitters (siehe PLAN.md Abschnitt 4,
    Schritt 5), die als zusammenhängende "Wolke" über mehrere Pixel streuen können. Clustert
    daher über transitive Nachbarschaft (Connected Components), nicht nur direkten Abstand zum
    jeweils stärksten Treffer, und behält je Cluster den Kandidaten mit dem höchsten SNR."""
    n = len(candidates)
    positions = np.array([c.position for c in candidates], dtype=np.float64)
    visited = np.zeros(n, dtype=bool)
    components: list[list[int]] = []

    for start in range(n):
        if visited[start]:
            continue
        visited[start] = True
        component = [start]
        pending = [start]
        while pending:
            current = pending.pop()
            distances = np.hypot(
                positions[:, 0] - positions[current, 0], positions[:, 1] - positions[current, 1]
            )
            neighbors = np.nonzero((distances <= position_tolerance) & ~visited)[0]
            for neighbor in neighbors:
                visited[neighbor] = True
                component.append(int(neighbor))
                pending.append(int(neighbor))
        components.append(component)

    results = []
    for component in components:
        best = max((candidates[i] for i in component), key=lambda c: c.snr)
        results.append(
            DetectionResult(
                vector=best.vector,
                position=best.position,
                snr=best.snr,
                peak_value=best.peak_value,
                thumbnail=_extract_thumbnail(best.image, best.position, thumbnail_size),
            )
        )
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
