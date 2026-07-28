from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder

from core.io_fits import FitsFrame, FrameStack


@dataclass
class StarList:
    x: np.ndarray
    y: np.ndarray
    flux: np.ndarray

    def __len__(self) -> int:
        return len(self.x)


@dataclass
class FrameAlignment:
    dx: float
    dy: float
    n_matches: int


@dataclass
class RegisteredFrame:
    frame: FitsFrame
    stars: StarList
    alignment: FrameAlignment


@dataclass
class RegisteredStack:
    reference_index: int
    frames: list[RegisteredFrame]

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> RegisteredFrame:
        return self.frames[index]


def detect_stars(data: np.ndarray, fwhm: float = 3.0, threshold_sigma: float = 5.0) -> StarList:
    """Sternfelderkennung via photutils DAOStarFinder, sortiert nach Helligkeit (Flux)."""
    _, median, std = sigma_clipped_stats(data, sigma=3.0)
    finder = DAOStarFinder(fwhm=fwhm, threshold=threshold_sigma * std)
    sources = finder(data - median)
    if sources is None or len(sources) == 0:
        empty = np.array([], dtype=np.float64)
        return StarList(x=empty, y=empty, flux=empty)

    sources.sort("flux", reverse=True)
    x_col = "x_centroid" if "x_centroid" in sources.colnames else "xcentroid"
    y_col = "y_centroid" if "y_centroid" in sources.colnames else "ycentroid"
    return StarList(
        x=np.asarray(sources[x_col], dtype=np.float64),
        y=np.asarray(sources[y_col], dtype=np.float64),
        flux=np.asarray(sources["flux"], dtype=np.float64),
    )


def estimate_shift(
    reference: StarList,
    target: StarList,
    max_stars: int = 25,
    bin_size: float = 1.0,
    tolerance: float = 2.0,
) -> FrameAlignment:
    """Translations-Shift zwischen zwei Sternfeldern via Shift-Voting (Histogram der
    paarweisen Offsets zwischen den hellsten Sternen). Robust gegen Fehldetektionen,
    setzt vernachlässigbare Feldrotation zwischen den Frames voraus."""
    ref_x, ref_y = reference.x[:max_stars], reference.y[:max_stars]
    tgt_x, tgt_y = target.x[:max_stars], target.y[:max_stars]
    if ref_x.size == 0 or tgt_x.size == 0:
        return FrameAlignment(dx=0.0, dy=0.0, n_matches=0)

    dx_all = (tgt_x[np.newaxis, :] - ref_x[:, np.newaxis]).ravel()
    dy_all = (tgt_y[np.newaxis, :] - ref_y[:, np.newaxis]).ravel()

    bins = list(zip(np.round(dx_all / bin_size), np.round(dy_all / bin_size)))
    (best_bin_dx, best_bin_dy), _ = Counter(bins).most_common(1)[0]
    best_dx = best_bin_dx * bin_size
    best_dy = best_bin_dy * bin_size

    mask = (np.abs(dx_all - best_dx) <= tolerance) & (np.abs(dy_all - best_dy) <= tolerance)
    if not np.any(mask):
        return FrameAlignment(dx=float(best_dx), dy=float(best_dy), n_matches=0)

    return FrameAlignment(
        dx=float(dx_all[mask].mean()),
        dy=float(dy_all[mask].mean()),
        n_matches=int(mask.sum()),
    )


def register_stack(
    stack: FrameStack,
    reference_index: int = 0,
    fwhm: float = 3.0,
    threshold_sigma: float = 5.0,
) -> RegisteredStack:
    star_lists = [
        detect_stars(frame.data, fwhm=fwhm, threshold_sigma=threshold_sigma)
        for frame in stack.frames
    ]
    reference_stars = star_lists[reference_index]

    registered = [
        RegisteredFrame(frame=frame, stars=stars, alignment=estimate_shift(reference_stars, stars))
        for frame, stars in zip(stack.frames, star_lists, strict=True)
    ]
    return RegisteredStack(reference_index=reference_index, frames=registered)
