import numpy as np
import pytest

from core.detection import DetectionResult
from core.project import ProjectStore
from core.synthetic_tracking import VelocityVector


@pytest.fixture
def store(tmp_path):
    project_store = ProjectStore(tmp_path / "test.db")
    yield project_store
    project_store.close()


def _make_detection(seed: int, confirmed: bool | None = None) -> DetectionResult:
    rng = np.random.default_rng(seed)
    return DetectionResult(
        vector=VelocityVector(speed_arcsec_per_min=1.5 + seed, angle_deg=30.0 * seed),
        position=(10 + seed, 20 + seed),
        snr=50.0 - seed,
        peak_value=1000.0 + seed,
        thumbnail=rng.uniform(0, 1000, size=(16, 16)),
        confirmed=confirmed,
    )


def test_create_and_list_projects(store):
    project = store.create_project("Testfeld", r"C:\fits\testfeld", reference_index=2)

    assert project.id is not None
    assert project.reference_index == 2

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "Testfeld"
    assert projects[0].fits_folder == r"C:\fits\testfeld"


def test_get_project_missing_raises(store):
    with pytest.raises(KeyError):
        store.get_project(999)


def test_delete_project_cascades_detections(store):
    project = store.create_project("Test", "/some/folder")
    store.save_detections(project.id, [_make_detection(0)])

    store.delete_project(project.id)

    assert store.list_projects() == []
    assert store.load_detections(project.id) == []


def test_save_and_load_detections_roundtrip(store):
    project = store.create_project("Test", "/some/folder")
    detections = [
        _make_detection(0, confirmed=True),
        _make_detection(1, confirmed=False),
        _make_detection(2, confirmed=None),
    ]

    store.save_detections(project.id, detections)
    loaded = sorted(store.load_detections(project.id), key=lambda d: d.peak_value)

    assert len(loaded) == 3
    originals = sorted(detections, key=lambda d: d.peak_value)
    for original, restored in zip(originals, loaded, strict=True):
        assert restored.vector == original.vector
        assert restored.position == original.position
        assert restored.snr == pytest.approx(original.snr)
        assert restored.peak_value == pytest.approx(original.peak_value)
        assert restored.confirmed == original.confirmed
        np.testing.assert_allclose(restored.thumbnail, original.thumbnail)


def test_save_detections_replaces_previous(store):
    project = store.create_project("Test", "/some/folder")
    store.save_detections(project.id, [_make_detection(0), _make_detection(1)])

    store.save_detections(project.id, [_make_detection(2)])

    loaded = store.load_detections(project.id)
    assert len(loaded) == 1


def test_save_preset_and_overwrite(store):
    preset = store.save_preset("Schnelle NEOs", "search", {"speed_step": 1.0})
    assert preset.params == {"speed_step": 1.0}

    updated = store.save_preset("Schnelle NEOs", "search", {"speed_step": 2.0})
    assert updated.id == preset.id

    presets = store.list_presets("search")
    assert len(presets) == 1
    assert presets[0].params == {"speed_step": 2.0}


def test_list_presets_filters_by_kind(store):
    store.save_preset("A", "search", {})
    store.save_preset("B", "astrometry", {})

    assert [p.name for p in store.list_presets("search")] == ["A"]
    assert [p.name for p in store.list_presets("astrometry")] == ["B"]


def test_delete_preset(store):
    preset = store.save_preset("A", "search", {})

    store.delete_preset(preset.id)

    assert store.list_presets("search") == []
