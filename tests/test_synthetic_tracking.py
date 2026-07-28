from pathlib import Path

import numpy as np
import pytest

from core.alignment import FrameAlignment, RegisteredFrame, RegisteredStack, StarList
from core.io_fits import FitsFrame, FrameStack
from core.synthetic_tracking import (
    VelocityVector,
    build_velocity_grid,
    evaluate_vector,
    frame_elapsed_minutes,
    search_velocity_grid,
)

SIZE = 64
PIXEL_SCALE_ARCSEC = 1.0  # 1 arcsec/px -> arcsec/min-Geschwindigkeiten sind direkt px/min
N_FRAMES = 5
START_X, START_Y = 15.0, 30.0
TRUE_SPEED = 3.0  # arcsec/min == px/min bei PIXEL_SCALE_ARCSEC=1.0
TRUE_ANGLE = 0.0  # entlang +x


def _make_frame(index: int, star_x: float, star_y: float) -> FitsFrame:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    rng = np.random.default_rng(index)
    data = np.full((SIZE, SIZE), 50.0, dtype=np.float64) + rng.normal(scale=1.0, size=(SIZE, SIZE))
    data += 500.0 * np.exp(-(((x - star_x) ** 2 + (y - star_y) ** 2) / (2 * 1.5**2)))
    return FitsFrame(
        path=Path(f"frame_{index:03d}.fits"),
        data=data.astype(np.float32),
        header={},
        wcs=None,
        obs_time=f"2026-01-01T00:{index:02d}:00",
    )


def _make_moving_object_stack() -> FrameStack:
    frames = [
        _make_frame(i, START_X + TRUE_SPEED * i, START_Y) for i in range(N_FRAMES)
    ]
    return FrameStack(frames=frames)


def _zero_shift_registered_stack(stack: FrameStack) -> RegisteredStack:
    empty_stars = StarList(x=np.array([]), y=np.array([]), flux=np.array([]))
    frames = [
        RegisteredFrame(frame=frame, stars=empty_stars, alignment=FrameAlignment(0.0, 0.0, 0))
        for frame in stack.frames
    ]
    return RegisteredStack(reference_index=0, frames=frames)


def test_build_velocity_grid_covers_speed_and_angle_range():
    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(1.0, 3.0), speed_step_arcsec_per_min=1.0, angle_step_deg=90.0
    )

    assert len(grid) == 3 * 4  # 3 Geschwindigkeiten x 4 Winkel (0, 90, 180, 270)
    assert VelocityVector(speed_arcsec_per_min=2.0, angle_deg=90.0) in grid


def test_frame_elapsed_minutes_relative_to_reference():
    stack = _make_moving_object_stack()
    obs_times = [f.obs_time for f in stack.frames]

    elapsed = frame_elapsed_minutes(obs_times, reference_index=0)

    assert elapsed == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0], abs=1e-6)


def test_correct_vector_yields_higher_snr_than_wrong_vectors():
    stack = _make_moving_object_stack()
    registered = _zero_shift_registered_stack(stack)

    correct = VelocityVector(speed_arcsec_per_min=TRUE_SPEED, angle_deg=TRUE_ANGLE)
    wrong_direction = VelocityVector(speed_arcsec_per_min=TRUE_SPEED, angle_deg=180.0)
    stationary = VelocityVector(speed_arcsec_per_min=0.0, angle_deg=0.0)

    result_correct = evaluate_vector(stack, registered, correct, PIXEL_SCALE_ARCSEC)
    result_wrong = evaluate_vector(stack, registered, wrong_direction, PIXEL_SCALE_ARCSEC)
    result_stationary = evaluate_vector(stack, registered, stationary, PIXEL_SCALE_ARCSEC)

    assert result_correct.snr > result_wrong.snr
    assert result_correct.snr > result_stationary.snr
    # Der Peak sollte an der Referenzposition (y, x) des Objekts im Referenzframe liegen.
    assert result_correct.peak_position == pytest.approx((START_Y, START_X), abs=1)


def test_search_velocity_grid_finds_correct_vector_as_best():
    stack = _make_moving_object_stack()
    registered = _zero_shift_registered_stack(stack)

    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(0.0, 6.0), speed_step_arcsec_per_min=1.0, angle_step_deg=45.0
    )
    results = search_velocity_grid(stack, registered, grid, PIXEL_SCALE_ARCSEC)

    best = max(results, key=lambda r: r.snr)

    assert best.vector.speed_arcsec_per_min == pytest.approx(TRUE_SPEED, abs=1e-6)
    assert best.vector.angle_deg == pytest.approx(TRUE_ANGLE, abs=1e-6)
