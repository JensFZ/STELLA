# Benchmark: CPU-Loop vs. PyTorch-Batch (Phase 4)

Vergleicht `core.synthetic_tracking.search_velocity_grid` (Phase 3, sequenzielle
Python-Schleife über das Vektor-Gitter) mit `core.gpu_tracking.search_velocity_grid_torch`
(Phase 4, gesamtes Vektor-Gitter als eine gebatchte PyTorch-Tensor-Operation).

Ausführen:

```bash
python benchmarks/bench_synthetic_tracking.py
```

## Setup

- Bildgröße: 256×256 px, 10 Frames, 126 Vektoren im Suchgitter
  (Geschwindigkeit 0–6 arcsec/min in 1er-Schritten × Winkel in 20°-Schritten)

## Ergebnis (dieser Rechner)

- **Hardware:** Intel HD Graphics 520 (integriert) — keine NVIDIA/CUDA-, keine Apple-Silicon/MPS-GPU
- **PyTorch:** 2.13.0+cpu (CPU-only-Build), `torch.cuda.is_available() == False`,
  `torch.backends.mps.is_available() == False`
- **Gewähltes Gerät:** `cpu` (automatischer Fallback über `core.gpu_tracking.get_device()`)

| Implementierung | Zeit  | Bestes Ergebnis |
|---|---|---|
| CPU-Schleife (Phase 3) | 13.8 s | speed=1.0 arcsec/min, angle=20°, SNR=884.0 |
| PyTorch-Batch, Gerät `cpu` (Phase 4) | 13.9 s | speed=1.0 arcsec/min, angle=20°, SNR=884.0 |
| **Speedup** | **0.99×** | — |

Beide Implementierungen finden denselben besten Vektor mit identischer SNR — die
GPU-Batch-Logik ist korrekt äquivalent zur CPU-Referenz (siehe `tests/test_gpu_tracking.py`).

## Einordnung

Auf **CPU-only-Hardware** bringt die gebatchte PyTorch-Variante hier keinen Vorteil
(~1×): scipys `ndimage.shift` ist eine bereits optimierte C-Routine, während der
Batch-Ansatz einen einzigen sehr großen Tensor (`n_vektoren × n_frames × H × W`,
hier ≈ 330 MB) aufbaut und per `grid_sample` verarbeitet — auf der CPU ohne
massive Parallelität kompensiert dieser Overhead den Vorteil des Batchings.

Der eigentliche Vorteil des in `core/gpu_tracking.py` implementierten Batch-Ansatzes
entsteht auf **CUDA- oder MPS-Hardware**, wo `grid_sample` über tausende Kerne parallel
läuft statt die 126 Vektoren seriell in Python abzuarbeiten (der GPU-kritische Pfad laut
`PLAN.md` Abschnitt 4). Das konnte auf diesem Rechner mangels dedizierter GPU nicht
gemessen werden — `core.gpu_tracking.get_device()` wählt automatisch CUDA bzw. MPS,
sobald eines verfügbar ist; auf einer solchen Maschine kann derselbe Benchmark erneut
ausgeführt werden, um den tatsächlichen Speedup zu dokumentieren.

## Wichtiger Nebenfund beim Erstellen dieses Benchmarks

Der ursprüngliche SNR-Vergleich zeigte einen groben Unterschied zwischen CPU- und
GPU-Ergebnis (SNR 881 vs. 44 für denselben Vektor). Ursache war **keine** fehlerhafte
Shift-Logik, sondern eine unbehandelte Rand-Zone: Shift-and-Stack erzeugt an den
Bildrändern Zero-Padding-Bereiche (proportional zur Shift-Größe des jeweiligen Vektors),
die die Hintergrundstatistik (`sigma_clipped_stats`) verzerrten und Vektoren mit kleineren
Shifts künstlich bevorzugten. Behoben durch `core.synthetic_tracking.required_border_margin`
+ `crop_valid_region`, die diese Zone vor Peak-Suche und Hintergrundschätzung ausschließen —
gilt für CPU- und GPU-Pfad gleichermaßen (`build_stack_result` wird von beiden genutzt).
