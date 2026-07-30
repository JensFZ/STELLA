from pathlib import Path

import numpy as np
import pytest
import torch

from core.alignment import FrameAlignment, RegisteredFrame, RegisteredStack, StarList
from core.gpu_tracking import _max_vectors_per_batch, get_device, search_velocity_grid_torch
from core.io_fits import FitsFrame, FrameStack
from core.synthetic_tracking import VelocityVector, build_velocity_grid, search_velocity_grid

SIZE = 48
PIXEL_SCALE_ARCSEC = 1.0
N_FRAMES = 4
START_X, START_Y = 12.0, 20.0
TRUE_SPEED = 2.5
TRUE_ANGLE = 30.0


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
    angle_rad = np.radians(TRUE_ANGLE)
    frames = [
        _make_frame(
            i,
            START_X + TRUE_SPEED * i * np.cos(angle_rad),
            START_Y + TRUE_SPEED * i * np.sin(angle_rad),
        )
        for i in range(N_FRAMES)
    ]
    return FrameStack(frames=frames)


def _zero_shift_registered_stack(stack: FrameStack) -> RegisteredStack:
    empty_stars = StarList(x=np.array([]), y=np.array([]), flux=np.array([]))
    frames = [
        RegisteredFrame(frame=frame, stars=empty_stars, alignment=FrameAlignment(0.0, 0.0, 0))
        for frame in stack.frames
    ]
    return RegisteredStack(reference_index=0, frames=frames)


def test_get_device_respects_explicit_preference():
    assert get_device(prefer="cpu") == torch.device("cpu")


def test_torch_batch_matches_numpy_reference():
    stack = _make_moving_object_stack()
    registered = _zero_shift_registered_stack(stack)
    grid = [
        VelocityVector(speed_arcsec_per_min=TRUE_SPEED, angle_deg=TRUE_ANGLE),
        VelocityVector(speed_arcsec_per_min=0.0, angle_deg=0.0),
        VelocityVector(speed_arcsec_per_min=TRUE_SPEED, angle_deg=TRUE_ANGLE + 180.0),
    ]

    cpu_results = search_velocity_grid(stack, registered, grid, PIXEL_SCALE_ARCSEC)
    torch_results = search_velocity_grid_torch(
        stack, registered, grid, PIXEL_SCALE_ARCSEC, device=get_device(prefer="cpu")
    )

    # Am Bildrand behandeln scipy (Spline-Extrapolation) und PyTorch grid_sample
    # (Zero-Padding, align_corners=False) Randpixel leicht unterschiedlich; das ist eine
    # erwartete Konvention-Differenz, kein Logikfehler. Der Vergleich beschränkt sich daher
    # auf den vom Rand unabhängigen Bildinnenbereich.
    margin = 10
    for cpu_result, torch_result in zip(cpu_results, torch_results, strict=True):
        assert cpu_result.vector == torch_result.vector
        cpu_interior = cpu_result.image[margin:-margin, margin:-margin]
        torch_interior = torch_result.image[margin:-margin, margin:-margin]
        np.testing.assert_allclose(cpu_interior, torch_interior, atol=1.0, rtol=1e-3)

    # Der Peak-Wert des tatsächlich zutreffenden Vektors liegt im Bildinneren und muss daher
    # zwischen den Implementierungen übereinstimmen. Die volle SNR-Statistik ist hier nicht
    # geeignet, da sie Median/Std über das gesamte (im Test sehr kleine) Bild bildet und damit
    # den oben beschriebenen Rand-Effekt überproportional gewichtet.
    cpu_correct, torch_correct = cpu_results[0], torch_results[0]
    assert cpu_correct.peak_value == pytest.approx(torch_correct.peak_value, rel=0.02)


def test_torch_grid_search_finds_correct_vector():
    stack = _make_moving_object_stack()
    registered = _zero_shift_registered_stack(stack)
    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(0.0, 5.0), speed_step_arcsec_per_min=1.25, angle_step_deg=30.0
    )

    results = search_velocity_grid_torch(
        stack, registered, grid, PIXEL_SCALE_ARCSEC, device=get_device(prefer="cpu")
    )
    best = max(results, key=lambda r: r.snr)

    assert best.vector.speed_arcsec_per_min == pytest.approx(TRUE_SPEED, abs=1e-6)
    assert best.vector.angle_deg == pytest.approx(TRUE_ANGLE, abs=1e-6)


def test_max_vectors_per_batch_shrinks_with_frame_and_image_size():
    """Reproduziert die Größenordnung des OOM-Absturzes (RuntimeError beim Allokieren von
    ~2,75 GB): ein echter Suchlauf mit ~83 Frames bei 960x540 und einem für den Suchdialog
    typischen Gitter von ~240 Vektoren hätte mit der alten, unbegrenzten Implementierung
    einen einzigen Tensor dieser Größe angelegt. Die Blockgröße muss das Gitter deutlich
    unterteilen, nicht als ein einziger Block durchlaufen."""
    batch_size = _max_vectors_per_batch(n_frames=83, height=540, width=960)

    assert 1 <= batch_size < 240


def test_max_vectors_per_batch_never_returns_zero():
    """Selbst bei einem winzigen Budget muss mindestens ein Vektor pro Durchlauf möglich
    bleiben -- sonst bricht die äußere Schleife in search_velocity_grid_torch nie ab."""
    batch_size = _max_vectors_per_batch(
        n_frames=1000, height=4000, width=4000, memory_budget_bytes=1
    )

    assert batch_size == 1


def test_max_vectors_per_batch_scales_inversely_with_frame_count():
    small = _max_vectors_per_batch(n_frames=10, height=100, width=100)
    large = _max_vectors_per_batch(n_frames=100, height=100, width=100)

    assert large < small


def test_torch_batch_forced_into_multiple_batches_matches_single_batch():
    """Kernprobe für die interne Unterteilung in search_velocity_grid_torch: ein winziges
    Speicherbudget zwingt sie zu vielen Ein-Vektor-Durchläufen statt einem einzigen. Das
    Ergebnis muss trotzdem exakt dasselbe sein wie ohne Unterteilung -- sonst hätte die
    Umstellung von einer Tensor-Operation auf eine Schleife über Blöcke die Zuordnung von
    Vektor zu Ergebnis verschoben oder Werte verändert."""
    stack = _make_moving_object_stack()
    registered = _zero_shift_registered_stack(stack)
    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(0.0, 5.0), speed_step_arcsec_per_min=1.25, angle_step_deg=30.0
    )
    device = get_device(prefer="cpu")

    single_batch = search_velocity_grid_torch(stack, registered, grid, PIXEL_SCALE_ARCSEC, device)
    forced_batches = search_velocity_grid_torch(
        stack, registered, grid, PIXEL_SCALE_ARCSEC, device, memory_budget_bytes=1
    )

    assert len(forced_batches) == len(single_batch) == len(grid)
    for expected, actual in zip(single_batch, forced_batches, strict=True):
        assert actual.vector == expected.vector
        assert actual.border_margin == expected.border_margin
        np.testing.assert_array_equal(actual.image, expected.image)
