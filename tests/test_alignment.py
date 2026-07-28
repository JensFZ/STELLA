from pathlib import Path

import numpy as np
import pytest

from core.alignment import detect_stars, estimate_shift, register_stack
from core.io_fits import FitsFrame, FrameStack


def _make_star_field(star_positions: list[tuple[float, float]], size: int = 128) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    data = np.full((size, size), 50.0, dtype=np.float64)
    rng = np.random.default_rng(0)
    data += rng.normal(scale=1.0, size=data.shape)
    for star_x, star_y in star_positions:
        data += 2000.0 * np.exp(-(((x - star_x) ** 2 + (y - star_y) ** 2) / (2 * 2.0**2)))
    return data.astype(np.float32)


STAR_POSITIONS = [(20.0, 30.0), (80.0, 40.0), (60.0, 90.0), (100.0, 100.0)]


def test_detect_stars_finds_expected_count():
    data = _make_star_field(STAR_POSITIONS)

    stars = detect_stars(data, fwhm=3.0, threshold_sigma=5.0)

    assert len(stars) == len(STAR_POSITIONS)


def test_estimate_shift_recovers_known_translation():
    shift_x, shift_y = 5.3, -3.7
    reference_data = _make_star_field(STAR_POSITIONS)
    shifted_positions = [(x + shift_x, y + shift_y) for x, y in STAR_POSITIONS]
    target_data = _make_star_field(shifted_positions)

    reference_stars = detect_stars(reference_data)
    target_stars = detect_stars(target_data)
    alignment = estimate_shift(reference_stars, target_stars)

    assert alignment.n_matches == len(STAR_POSITIONS)
    assert alignment.dx == pytest.approx(shift_x, abs=0.5)
    assert alignment.dy == pytest.approx(shift_y, abs=0.5)


def test_register_stack_zero_shift_for_reference_frame():
    data = _make_star_field(STAR_POSITIONS)
    frame = FitsFrame(path=Path("ref.fits"), data=data, header={}, wcs=None, obs_time=None)
    stack = FrameStack(frames=[frame, frame])

    registered = register_stack(stack, reference_index=0)

    ref_alignment = registered[0].alignment
    assert ref_alignment.dx == pytest.approx(0.0, abs=0.2)
    assert ref_alignment.dy == pytest.approx(0.0, abs=0.2)
