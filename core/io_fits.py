from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

FITS_EXTENSIONS = {".fits", ".fit", ".fts"}


@dataclass
class FitsFrame:
    path: Path
    data: np.ndarray
    header: fits.Header
    wcs: WCS | None
    obs_time: str | None


@dataclass
class FrameStack:
    frames: list[FitsFrame]

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> FitsFrame:
        return self.frames[index]


def find_fits_files(folder: Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in FITS_EXTENSIONS)


def load_fits_frame(path: Path) -> FitsFrame:
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        data = np.asarray(hdu.data, dtype=np.float32)
        header = hdu.header
        try:
            wcs = WCS(header)
            wcs = wcs if wcs.has_celestial else None
        except Exception:
            wcs = None
        obs_time = header.get("DATE-OBS")
    return FitsFrame(path=Path(path), data=data, header=header, wcs=wcs, obs_time=obs_time)


def load_frame_stack(folder: Path) -> FrameStack:
    return FrameStack(frames=[load_fits_frame(p) for p in find_fits_files(folder)])


def stretch_to_uint8(data: np.ndarray, low_pct: float = 1.0, high_pct: float = 99.5) -> np.ndarray:
    """Percentile-basiertes Histogram-Stretch nach 0-255 uint8."""
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros_like(data, dtype=np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        hi = lo + 1.0
    clipped = np.clip((np.nan_to_num(data, nan=lo) - lo) / (hi - lo), 0.0, 1.0)
    return (clipped * 255).astype(np.uint8)


def make_thumbnail(data: np.ndarray, size: int = 128) -> np.ndarray:
    """Downsampled, gestrecktes Vorschaubild (uint8) mit max. Kantenlänge `size`."""
    h, w = data.shape[-2:]
    step = max(1, max(h, w) // size)
    return stretch_to_uint8(data[::step, ::step])
