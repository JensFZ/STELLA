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


#: Speicherobergrenze für einen einzelnen grid_sample()-Durchlauf. workers.py zerlegt das
#: Vektor-Gitter zwar bereits in Blöcke (Fortschrittsanzeige), aber deren Größe richtet sich
#: nach der Blockanzahl, nicht nach Frame- oder Bildgröße — bei vielen großen Frames kann
#: schon ein einzelner Block mehr Speicher verlangen, als vorhanden ist. Diese Schwelle
#: sichert unabhängig davon direkt an der Stelle ab, an der der Speicherbedarf tatsächlich
#: entsteht. 512 MiB ist bewusst konservativ gewählt, nicht an ein bestimmtes System
#: angepasst — siehe _PEAK_TENSOR_MULTIPLIER unten für die Herleitung.
DEFAULT_GPU_MEMORY_BUDGET_BYTES = 512 * 1024**2

_BYTES_PER_FLOAT32 = 4

# Innerhalb eines Batches sind gleichzeitig groß (jeweils Batch-Vektoren × Frames × H × W
# Elemente, `del` direkt nach letzter Verwendung): src_row, src_col (2), grid_x, grid_y (2),
# sampling_grid (zählt doppelt wegen der letzten Dimension der Größe 2), frames_expanded,
# shifted (2). Macht 8 "Einheiten" Rohbedarf; der Faktor 10 lässt Luft für PyTorchs internen
# Allocator (Fragmentierung, Zwischenkopien in grid_sample selbst).
_PEAK_TENSOR_MULTIPLIER = 10


def _max_vectors_per_batch(
    n_frames: int,
    height: int,
    width: int,
    memory_budget_bytes: int = DEFAULT_GPU_MEMORY_BUDGET_BYTES,
) -> int:
    """Wie viele Vektoren lassen sich in einem grid_sample()-Aufruf verarbeiten, ohne das
    Speicherbudget zu überschreiten? Mindestens 1 — reicht das Budget dafür nicht, ist das
    ein Hinweis auf zu wenig Speicher für die Bildgröße, kein Grund, ganz aufzugeben."""
    bytes_per_vector = n_frames * height * width * _BYTES_PER_FLOAT32 * _PEAK_TENSOR_MULTIPLIER
    return max(1, memory_budget_bytes // max(bytes_per_vector, 1))


def search_velocity_grid_torch(
    stack: FrameStack,
    registered: RegisteredStack,
    grid: list[VelocityVector],
    pixel_scale_arcsec: float,
    device: torch.device | None = None,
    memory_budget_bytes: int = DEFAULT_GPU_MEMORY_BUDGET_BYTES,
) -> list[StackResult]:
    """GPU-Batch-Referenzimplementierung von Phase 3: verschiebt und summiert die Frames für
    das Vektor-Gitter blockweise über grid_sample(), statt das Gitter (wie in
    core.synthetic_tracking) mit einer Python-Schleife pro Vektor abzuarbeiten. Nutzt bei
    fehlender GPU automatisch den CPU-Pfad (gleicher Code, `device="cpu"`).

    `memory_budget_bytes` steuert die interne Blockgröße (siehe _max_vectors_per_batch) und
    ist als Parameter vor allem zum Testen gedacht — um gezielt mehrere Blöcke zu erzwingen,
    ohne ein Gitter zu bauen, das dafür groß genug wäre."""
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
    # von Peak-Suche/Hintergrundstatistik ausgeschlossen werden muss. Klein (n_vectors x
    # n_frames), unabhängig von der Bildgröße — braucht keine Unterteilung.
    max_abs_shift = torch.maximum(total_dx_2d.abs().amax(dim=1), total_dy_2d.abs().amax(dim=1))
    margins = torch.ceil(max_abs_shift).to("cpu").numpy().astype(int) + 1

    # Ziel wie in core.synthetic_tracking.shift_and_stack: output[row, col] = input[row+dy, col+dx].
    row_idx = torch.arange(height, device=device, dtype=torch.float32)
    col_idx = torch.arange(width, device=device, dtype=torch.float32)
    base_row, base_col = torch.meshgrid(row_idx, col_idx, indexing="ij")  # (H, W)

    # Der eigentliche grid_sample()-Aufruf vervielfacht die Frames je Vektor im Batch — ohne
    # Deckelung reißt das bei realen Datenmengen (viele/große Frames) den Speicher, selbst
    # wenn workers.py das Gitter von außen bereits in Blöcke zerlegt: ein einzelner Block
    # kann für sich schon zu groß sein (siehe _max_vectors_per_batch). Deshalb hier eine
    # zweite, interne Unterteilung, die nur von Frame- und Bildgröße abhängt.
    batch_size = _max_vectors_per_batch(n_frames, height, width, memory_budget_bytes)

    results: list[StackResult] = []
    for start in range(0, n_vectors, batch_size):
        batch_dx = total_dx_2d[start : start + batch_size].reshape(-1)  # (batch*n_frames,)
        batch_dy = total_dy_2d[start : start + batch_size].reshape(-1)
        n_batch_vectors = batch_dx.shape[0] // n_frames

        src_row = base_row[None, :, :] + batch_dy[:, None, None]  # (batch*n_frames, H, W)
        src_col = base_col[None, :, :] + batch_dx[:, None, None]
        del batch_dx, batch_dy

        # grid_sample erwartet normalisierte (x, y)-Koordinaten in [-1, 1], align_corners=False:
        # norm = (2 * pixel_index + 1) / size - 1.
        grid_x = (2.0 * src_col + 1.0) / width - 1.0
        grid_y = (2.0 * src_row + 1.0) / height - 1.0
        del src_row, src_col
        sampling_grid = torch.stack((grid_x, grid_y), dim=-1)  # (batch*n_frames, H, W, 2)
        del grid_x, grid_y

        frames_expanded = (
            frames.unsqueeze(0)
            .expand(n_batch_vectors, n_frames, height, width)
            .reshape(n_batch_vectors * n_frames, 1, height, width)
        )

        shifted = F.grid_sample(
            frames_expanded,
            sampling_grid,
            mode="bilinear",
            padding_mode="zeros",
            align_corners=False,
        )  # (batch*n_frames, 1, H, W)
        del frames_expanded, sampling_grid

        stacked = shifted.reshape(n_batch_vectors, n_frames, height, width).sum(dim=1)
        stacked_np = stacked.to("cpu").numpy()
        del shifted, stacked

        for offset in range(n_batch_vectors):
            index = start + offset
            results.append(build_stack_result(grid[index], stacked_np[offset], int(margins[index])))

    return results
