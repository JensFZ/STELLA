from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

from core.alignment import RegisteredStack
from core.io_fits import FrameStack
from core.synthetic_tracking import (
    StackResult,
    VelocityVector,
    build_stack_result,
    frame_elapsed_minutes,
)


def get_device(prefer: str | None = None) -> torch.device:
    """Wählt CUDA > MPS > CPU. `prefer` erzwingt ein bestimmtes Gerät (für Tests/Benchmarks)."""
    if prefer is not None:
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def search_velocity_grid_torch(
    stack: FrameStack,
    registered: RegisteredStack,
    grid: list[VelocityVector],
    pixel_scale_arcsec: float,
    device: torch.device | None = None,
) -> list[StackResult]:
    """GPU-Batch-Referenzimplementierung von Phase 3: verschiebt und summiert alle Frames für
    das gesamte Vektor-Gitter in einer einzigen gebatchten Tensor-Operation, statt das Gitter
    (wie in core.synthetic_tracking) mit einer Python-Schleife sequenziell abzuarbeiten. Nutzt
    bei fehlender GPU automatisch den CPU-Pfad (gleicher Code, `device="cpu"`)."""
    device = device or get_device()
    reference_index = registered.reference_index
    obs_times = [frame.obs_time for frame in stack.frames]
    elapsed = frame_elapsed_minutes(obs_times, reference_index)

    n_frames = len(stack.frames)
    n_vectors = len(grid)
    height, width = stack.frames[reference_index].data.shape

    frames = torch.stack(
        [torch.from_numpy(frame.data.astype(np.float32)) for frame in stack.frames]
    ).to(device)  # (n_frames, H, W)

    star_dx = torch.tensor(
        [registered[i].alignment.dx for i in range(n_frames)], device=device, dtype=torch.float32
    )
    star_dy = torch.tensor(
        [registered[i].alignment.dy for i in range(n_frames)], device=device, dtype=torch.float32
    )
    elapsed_t = torch.as_tensor(elapsed, device=device, dtype=torch.float32)

    speeds_px = (
        torch.tensor([v.speed_arcsec_per_min for v in grid], device=device, dtype=torch.float32)
        / pixel_scale_arcsec
    )
    angles = torch.tensor(
        [np.radians(v.angle_deg) for v in grid], device=device, dtype=torch.float32
    )

    # (n_vectors, n_frames)
    obj_dx = speeds_px[:, None] * elapsed_t[None, :] * torch.cos(angles)[:, None]
    obj_dy = speeds_px[:, None] * elapsed_t[None, :] * torch.sin(angles)[:, None]
    total_dx_2d = star_dx[None, :] + obj_dx
    total_dy_2d = star_dy[None, :] + obj_dy

    # Rand, der pro Vektor durch Zero-Padding beim Zurückschieben mindestens eines Frames
    # beeinträchtigt sein kann (siehe core.synthetic_tracking.required_border_margin) und daher
    # von Peak-Suche/Hintergrundstatistik ausgeschlossen werden muss.
    max_abs_shift = torch.maximum(total_dx_2d.abs().amax(dim=1), total_dy_2d.abs().amax(dim=1))
    margins = (torch.ceil(max_abs_shift).to("cpu").numpy().astype(int) + 1)

    total_dx = total_dx_2d.reshape(-1)  # (n_vectors * n_frames,)
    total_dy = total_dy_2d.reshape(-1)

    # Ziel wie in core.synthetic_tracking.shift_and_stack: output[row, col] = input[row+dy, col+dx].
    row_idx = torch.arange(height, device=device, dtype=torch.float32)
    col_idx = torch.arange(width, device=device, dtype=torch.float32)
    base_row, base_col = torch.meshgrid(row_idx, col_idx, indexing="ij")  # (H, W)

    src_row = base_row[None, :, :] + total_dy[:, None, None]  # (n_vectors*n_frames, H, W)
    src_col = base_col[None, :, :] + total_dx[:, None, None]

    # grid_sample erwartet normalisierte (x, y)-Koordinaten in [-1, 1], align_corners=False:
    # norm = (2 * pixel_index + 1) / size - 1.
    grid_x = (2.0 * src_col + 1.0) / width - 1.0
    grid_y = (2.0 * src_row + 1.0) / height - 1.0
    sampling_grid = torch.stack((grid_x, grid_y), dim=-1)  # (n_vectors*n_frames, H, W, 2)

    frames_expanded = (
        frames.unsqueeze(0)
        .expand(n_vectors, n_frames, height, width)
        .reshape(n_vectors * n_frames, 1, height, width)
    )

    shifted = F.grid_sample(
        frames_expanded,
        sampling_grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=False,
    )  # (n_vectors*n_frames, 1, H, W)

    stacked = shifted.reshape(n_vectors, n_frames, height, width).sum(dim=1)  # (n_vectors, H, W)
    stacked_np = stacked.to("cpu").numpy()

    return [
        build_stack_result(vector, stacked_np[i], int(margins[i])) for i, vector in enumerate(grid)
    ]
