import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPropertyAnimation, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.views.workflow_panel import StepState, WorkflowPanel  # noqa: E402


def _is_pulsing(panel: WorkflowPanel, step: int) -> bool:
    row = panel._rows[step]
    return row._pulse.state() == QPropertyAnimation.State.Running


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _click(panel: WorkflowPanel, step: int) -> None:
    QTest.mouseClick(panel._rows[step], Qt.MouseButton.LeftButton)


def test_only_the_first_step_is_available_initially():
    _app()
    panel = WorkflowPanel()

    assert panel.state(WorkflowPanel.STEP_LOAD) == StepState.AVAILABLE
    for step in (
        WorkflowPanel.STEP_ALIGN,
        WorkflowPanel.STEP_DETECT,
        WorkflowPanel.STEP_ASTROMETRY,
        WorkflowPanel.STEP_EXPORT,
    ):
        assert panel.state(step) == StepState.LOCKED


def test_locked_steps_do_not_emit_activation():
    """Gesperrte Schritte dürfen nicht auslösbar sein — sonst liefe eine Aktion ohne ihre
    Voraussetzung."""
    _app()
    panel = WorkflowPanel()
    activated = []
    panel.step_activated.connect(activated.append)

    _click(panel, WorkflowPanel.STEP_DETECT)

    assert activated == []


def test_available_step_emits_its_index():
    _app()
    panel = WorkflowPanel()
    activated = []
    panel.step_activated.connect(activated.append)

    _click(panel, WorkflowPanel.STEP_LOAD)

    assert activated == [WorkflowPanel.STEP_LOAD]


def test_detail_text_is_shown_only_when_present():
    _app()
    panel = WorkflowPanel()

    panel.set_state(WorkflowPanel.STEP_LOAD, StepState.DONE, "258 Frames")
    assert panel._rows[WorkflowPanel.STEP_LOAD].detail_label.text() == "258 Frames"

    panel.set_state(WorkflowPanel.STEP_LOAD, StepState.AVAILABLE)
    assert panel._rows[WorkflowPanel.STEP_LOAD].detail_label.isHidden()


def test_reset_from_locks_all_later_steps():
    """Wird ein früherer Schritt erneut ausgeführt, gelten die späteren Ergebnisse nicht
    mehr und dürfen nicht weiter als erledigt erscheinen."""
    _app()
    panel = WorkflowPanel()
    for step in range(5):
        panel.set_state(step, StepState.DONE, "fertig")

    panel.reset_from(WorkflowPanel.STEP_DETECT)

    assert panel.state(WorkflowPanel.STEP_ALIGN) == StepState.DONE
    for step in (
        WorkflowPanel.STEP_DETECT,
        WorkflowPanel.STEP_ASTROMETRY,
        WorkflowPanel.STEP_EXPORT,
    ):
        assert panel.state(step) == StepState.LOCKED


def test_state_marker_does_not_accumulate_in_title():
    """Der Zustandsmarker wird dem Titel vorangestellt; bei wiederholtem Setzen darf er
    sich nicht aufsummieren."""
    _app()
    panel = WorkflowPanel()
    row = panel._rows[WorkflowPanel.STEP_LOAD]

    for state in (StepState.DONE, StepState.AVAILABLE, StepState.RUNNING, StepState.DONE):
        panel.set_state(WorkflowPanel.STEP_LOAD, state)

    assert row.title_label.text().count("FITS-Ordner laden") == 1
    assert row.title_label.text().startswith("✓")


def test_available_step_pulses():
    """Markiert den Schritt, an dem es weitergeht -- Ersatz für einen separaten
    "Weiter"-Button, der bei zwei parallel verfügbaren Schritten (STEP_DETECT und
    STEP_ASTROMETRY nach der Ausrichtung) ohnehin nur einen davon bevorzugen könnte."""
    _app()
    panel = WorkflowPanel()

    assert _is_pulsing(panel, WorkflowPanel.STEP_LOAD)


def test_pulse_stops_when_step_leaves_available_state():
    _app()
    panel = WorkflowPanel()
    row = panel._rows[WorkflowPanel.STEP_LOAD]

    panel.set_state(WorkflowPanel.STEP_LOAD, StepState.DONE, "1 Frame")

    assert not _is_pulsing(panel, WorkflowPanel.STEP_LOAD)
    assert row._opacity_effect.opacity() == 1.0


def test_locked_step_does_not_pulse():
    _app()
    panel = WorkflowPanel()

    assert not _is_pulsing(panel, WorkflowPanel.STEP_ALIGN)


def test_running_step_does_not_pulse():
    _app()
    panel = WorkflowPanel()

    panel.set_state(WorkflowPanel.STEP_LOAD, StepState.RUNNING)

    assert not _is_pulsing(panel, WorkflowPanel.STEP_LOAD)


def test_two_parallel_available_steps_both_pulse():
    """STEP_DETECT und STEP_ASTROMETRY werden nach der Ausrichtung gleichzeitig verfügbar
    (siehe main_window._on_align_finished) -- beide sind gleichwertige nächste Schritte und
    sollen das auch beide anzeigen."""
    _app()
    panel = WorkflowPanel()

    panel.set_state(WorkflowPanel.STEP_DETECT, StepState.AVAILABLE)
    panel.set_state(WorkflowPanel.STEP_ASTROMETRY, StepState.AVAILABLE)

    assert _is_pulsing(panel, WorkflowPanel.STEP_DETECT)
    assert _is_pulsing(panel, WorkflowPanel.STEP_ASTROMETRY)
