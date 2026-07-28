"""Benchmark: CPU-Python-Schleife (Phase 3) vs. PyTorch-Batch (Phase 4) für
Shift-and-Stack über ein Vektor-Gitter. Manuell ausführen:

    python benchmarks/bench_synthetic_tracking.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch

from core.alignment import FrameAlignment, RegisteredFrame, RegisteredStack, StarList
from core.gpu_tracking import get_device, search_velocity_grid_torch
from core.io_fits import FitsFrame, FrameStack
from core.synthetic_tracking import build_velocity_grid, search_velocity_grid

IMAGE_SIZE = 256
N_FRAMES = 10
PIXEL_SCALE_ARCSEC = 1.0


def _make_synthetic_stack(size: int, n_frames: int) -> FrameStack:
    y, x = np.mgrid[0:size, 0:size]
    frames = []
    for i in range(n_frames):
        rng = np.random.default_rng(i)
        data = np.full((size, size), 100.0, dtype=np.float64)
        data += rng.normal(scale=8.0, size=(size, size))
        star_x, star_y = size * 0.3 + i * 1.5, size * 0.6
        data += 2000.0 * np.exp(-(((x - star_x) ** 2 + (y - star_y) ** 2) / (2 * 2.5**2)))
        obj_x, obj_y = size * 0.2 + i * 2.5, size * 0.3 + i * 1.0
        data += 1200.0 * np.exp(-(((x - obj_x) ** 2 + (y - obj_y) ** 2) / (2 * 2.0**2)))
        frames.append(
            FitsFrame(
                path=Path(f"frame_{i:03d}.fits"),
                data=data.astype(np.float32),
                header={},
                wcs=None,
                obs_time=f"2026-01-01T00:{i:02d}:00",
            )
        )
    return FrameStack(frames=frames)


def _zero_shift_registered_stack(stack: FrameStack) -> RegisteredStack:
    empty_stars = StarList(x=np.array([]), y=np.array([]), flux=np.array([]))
    frames = [
        RegisteredFrame(frame=frame, stars=empty_stars, alignment=FrameAlignment(0.0, 0.0, 0))
        for frame in stack.frames
    ]
    return RegisteredStack(reference_index=0, frames=frames)


def main() -> None:
    stack = _make_synthetic_stack(IMAGE_SIZE, N_FRAMES)
    registered = _zero_shift_registered_stack(stack)
    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(0.0, 6.0), speed_step_arcsec_per_min=1.0, angle_step_deg=20.0
    )

    print(f"Bildgröße: {IMAGE_SIZE}x{IMAGE_SIZE}, Frames: {N_FRAMES}, Vektoren: {len(grid)}")
    print(
        f"PyTorch: {torch.__version__}, CUDA verfügbar: {torch.cuda.is_available()}, "
        f"MPS verfügbar: {torch.backends.mps.is_available()}"
    )
    device = get_device()
    print(f"Gewähltes Gerät: {device}")

    start = time.perf_counter()
    cpu_results = search_velocity_grid(stack, registered, grid, PIXEL_SCALE_ARCSEC)
    cpu_seconds = time.perf_counter() - start

    start = time.perf_counter()
    torch_results = search_velocity_grid_torch(
        stack, registered, grid, PIXEL_SCALE_ARCSEC, device=device
    )
    torch_seconds = time.perf_counter() - start

    best_cpu = max(cpu_results, key=lambda r: r.snr)
    best_torch = max(torch_results, key=lambda r: r.snr)

    print()
    print(f"CPU-Schleife (core.synthetic_tracking):     {cpu_seconds:7.3f} s")
    print(f"PyTorch-Batch (core.gpu_tracking, {device}):  {torch_seconds:7.3f} s")
    print(f"Speedup: {cpu_seconds / torch_seconds:.2f}x")
    print()
    print(f"Bester Vektor (CPU):   {best_cpu.vector}, SNR={best_cpu.snr:.1f}")
    print(f"Bester Vektor (Torch): {best_torch.vector}, SNR={best_torch.snr:.1f}")


if __name__ == "__main__":
    main()
