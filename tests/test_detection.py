from pathlib import Path

import numpy as np
import pytest

from core.alignment import FrameAlignment, RegisteredFrame, RegisteredStack, StarList
from core.detection import cluster_candidates, detect_candidates, find_candidate_peaks
from core.io_fits import FitsFrame, FrameStack
from core.synthetic_tracking import (
    VelocityVector,
    build_velocity_grid,
    evaluate_vector,
    search_velocity_grid,
)

SIZE = 80
PIXEL_SCALE_ARCSEC = 1.0
N_FRAMES = 4

OBJECT_A = {"start": (15.0, 20.0), "speed": 3.0, "angle": 0.0}
OBJECT_B = {"start": (55.0, 60.0), "speed": 2.0, "angle": 90.0}


def _object_position(obj: dict, frame_index: int) -> tuple[float, float]:
    angle_rad = np.radians(obj["angle"])
    start_x, start_y = obj["start"]
    x = start_x + obj["speed"] * frame_index * np.cos(angle_rad)
    y = start_y + obj["speed"] * frame_index * np.sin(angle_rad)
    return x, y


def _make_frame(index: int) -> FitsFrame:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    rng = np.random.default_rng(index)
    data = np.full((SIZE, SIZE), 50.0, dtype=np.float64) + rng.normal(scale=1.0, size=(SIZE, SIZE))
    for obj in (OBJECT_A, OBJECT_B):
        obj_x, obj_y = _object_position(obj, index)
        data += 800.0 * np.exp(-(((x - obj_x) ** 2 + (y - obj_y) ** 2) / (2 * 1.5**2)))
    return FitsFrame(
        path=Path(f"frame_{index:03d}.fits"),
        data=data.astype(np.float32),
        header={},
        wcs=None,
        obs_time=f"2026-01-01T00:{index:02d}:00",
    )


def _make_stack() -> FrameStack:
    return FrameStack(frames=[_make_frame(i) for i in range(N_FRAMES)])


def _zero_shift_registered_stack(stack: FrameStack) -> RegisteredStack:
    empty_stars = StarList(x=np.array([]), y=np.array([]), flux=np.array([]))
    frames = [
        RegisteredFrame(frame=frame, stars=empty_stars, alignment=FrameAlignment(0.0, 0.0, 0))
        for frame in stack.frames
    ]
    return RegisteredStack(reference_index=0, frames=frames)


def test_find_candidate_peaks_respects_threshold():
    stack = _make_stack()
    registered = _zero_shift_registered_stack(stack)
    vector = VelocityVector(speed_arcsec_per_min=OBJECT_A["speed"], angle_deg=OBJECT_A["angle"])
    result = evaluate_vector(stack, registered, vector, PIXEL_SCALE_ARCSEC)

    peaks_low = find_candidate_peaks(result, snr_threshold=3.0)
    peaks_impossible = find_candidate_peaks(result, snr_threshold=1e6)

    assert len(peaks_low) >= 1
    assert peaks_impossible == []


def test_true_vector_outranks_neighbours_across_the_grid():
    """Die SNR-Werte verschiedener Vektoren müssen vergleichbar sein: der tatsächlich
    zutreffende Vektor muss am Objekt den höchsten SNR liefern. Ohne Ausschluss der
    Zero-Padding-Randzone bekämen Vektoren mit kleinerem Shift zu gute Werte und würden
    den wahren Vektor in der Kandidatenliste verdrängen."""
    stack = _make_stack()
    registered = _zero_shift_registered_stack(stack)

    def best_snr_at_object(speed: float) -> float:
        vector = VelocityVector(speed_arcsec_per_min=speed, angle_deg=OBJECT_A["angle"])
        result = evaluate_vector(stack, registered, vector, PIXEL_SCALE_ARCSEC)
        peaks = find_candidate_peaks(result, snr_threshold=3.0)
        near = [
            c
            for c in peaks
            if abs(c.position[0] - OBJECT_A["start"][1]) <= 3
            and abs(c.position[1] - OBJECT_A["start"][0]) <= 3
        ]
        return max((c.snr for c in near), default=0.0)

    true_speed = OBJECT_A["speed"]
    assert best_snr_at_object(true_speed) > best_snr_at_object(true_speed - 1.0)
    assert best_snr_at_object(true_speed) > best_snr_at_object(true_speed + 1.0)


def test_cluster_candidates_does_not_chain_distant_objects_via_bridge():
    """Regressionsschutz gegen Single-Linkage-Verkettung: zwei weit auseinander liegende
    echte Objekte dürfen nicht verschmelzen, nur weil eine Kette schwacher Treffer sie
    verbindet — sonst verschwindet das schwächere Objekt komplett aus der Kandidatenliste."""
    from core.detection import Candidate

    image = np.zeros((200, 200))
    strong = Candidate(
        vector=VelocityVector(1.0, 0.0),
        position=(20, 20),
        snr=500.0,
        peak_value=5000.0,
        image=image,
    )
    weak = Candidate(
        vector=VelocityVector(2.0, 90.0),
        position=(20, 120),
        snr=80.0,
        peak_value=800.0,
        image=image,
    )
    # Lückenlose Brücke aus schwachen Treffern zwischen beiden Objekten (Abstand 2 px).
    bridge = [
        Candidate(
            vector=VelocityVector(1.0, 0.0),
            position=(20, col),
            snr=10.0,
            peak_value=100.0,
            image=image,
        )
        for col in range(22, 120, 2)
    ]

    clustered = cluster_candidates([strong, weak, *bridge], position_tolerance=3.0)

    positions = {d.position for d in clustered}
    assert (20, 20) in positions, "starkes Objekt fehlt"
    assert (20, 120) in positions, "schwaches Objekt wurde durch die Brücke verschluckt"


def test_cluster_candidates_merges_nearby_duplicates():
    from core.detection import Candidate

    image = np.zeros((20, 20))
    candidates = [
        Candidate(
            vector=VelocityVector(1.0, 0.0),
            position=(10, 10),
            snr=8.0,
            peak_value=100.0,
            image=image,
        ),
        Candidate(
            vector=VelocityVector(1.1, 5.0),
            position=(11, 10),
            snr=9.5,
            peak_value=110.0,
            image=image,
        ),
        Candidate(
            vector=VelocityVector(5.0, 90.0),
            position=(2, 2),
            snr=6.0,
            peak_value=80.0,
            image=image,
        ),
    ]

    clustered = cluster_candidates(candidates, position_tolerance=3.0)

    assert len(clustered) == 2
    assert clustered[0].position == (11, 10)  # höchster SNR im Cluster gewinnt
    assert clustered[0].snr == pytest.approx(9.5)


def test_detect_candidates_finds_both_independent_objects():
    # Bei einem groben Vektor-Gitter erzeugen auch leicht falsche Nachbarvektoren noch
    # schwache Peaks (Trail-Verschmierung) und gelegentlich reines Rauschen über der
    # SNR-Schwelle — das ist bei Synthetic Tracking normal (PLAN.md Phase 5: "false
    # positives sind normal", daher die manuelle Bestätigung/Verwerfung in der GUI).
    # Die beiden echten Objekte müssen sich aber klar als die SNR-stärksten Treffer abheben.
    stack = _make_stack()
    registered = _zero_shift_registered_stack(stack)
    grid = build_velocity_grid(
        speed_range_arcsec_per_min=(0.0, 4.0), speed_step_arcsec_per_min=1.0, angle_step_deg=30.0
    )
    results = search_velocity_grid(stack, registered, grid, PIXEL_SCALE_ARCSEC)

    detections = detect_candidates(results, snr_threshold=5.0, position_tolerance=3.0)

    assert len(detections) >= 2
    assert detections == sorted(detections, key=lambda d: -d.snr)

    top_two_positions = {(round(d.position[0]), round(d.position[1])) for d in detections[:2]}
    expected_a = (round(OBJECT_A["start"][1]), round(OBJECT_A["start"][0]))  # (row, col)
    expected_b = (round(OBJECT_B["start"][1]), round(OBJECT_B["start"][0]))
    for expected in (expected_a, expected_b):
        assert any(
            abs(p[0] - expected[0]) <= 2 and abs(p[1] - expected[1]) <= 2
            for p in top_two_positions
        )

    for detection in detections:
        assert detection.thumbnail.size > 0
        assert detection.confirmed is None
