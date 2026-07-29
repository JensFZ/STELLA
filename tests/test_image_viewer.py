import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from astropy.io import fits
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.alignment import register_stack  # noqa: E402
from core.io_fits import load_frame_stack  # noqa: E402
from gui.views.image_viewer import ImageViewer  # noqa: E402


def _write_fits(path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=100.0, scale=10.0, size=(32, 32)).astype(np.float32)
    fits.writeto(path, data, overwrite=True)


def _write_star_field_fits(
    path, star_positions: list[tuple[float, float]], size: int = 128
) -> None:
    y, x = np.mgrid[0:size, 0:size]
    rng = np.random.default_rng(0)
    data = np.full((size, size), 50.0, dtype=np.float64) + rng.normal(scale=1.0, size=(size, size))
    for star_x, star_y in star_positions:
        data += 2000.0 * np.exp(-(((x - star_x) ** 2 + (y - star_y) ** 2) / (2 * 2.0**2)))
    fits.writeto(path, data.astype(np.float32), overwrite=True)


def test_image_viewer_loads_stack_and_navigates(tmp_path):
    _app = QApplication.instance() or QApplication([])
    _write_fits(tmp_path / "a.fits", 1)
    _write_fits(tmp_path / "b.fits", 2)
    _write_fits(tmp_path / "c.fits", 3)
    stack = load_frame_stack(tmp_path)

    viewer = ImageViewer()
    viewer.set_stack(stack)

    assert viewer.thumbnail_list.count() == 3
    assert viewer.frame_slider.maximum() == 2
    assert "1 / 3" in viewer.frame_label.text()

    viewer.set_frame_index(2)

    assert "3 / 3" in viewer.frame_label.text()
    assert viewer.thumbnail_list.currentRow() == 2


def test_image_viewer_shows_star_overlay_after_registration(tmp_path):
    _app = QApplication.instance() or QApplication([])
    positions = [(20.0, 30.0), (80.0, 40.0), (60.0, 90.0)]
    _write_star_field_fits(tmp_path / "a.fits", positions)
    _write_star_field_fits(tmp_path / "b.fits", [(x + 4.0, y - 2.0) for x, y in positions])
    stack = load_frame_stack(tmp_path)
    registered = register_stack(stack, reference_index=0)

    viewer = ImageViewer()
    viewer.set_stack(stack)
    viewer.set_registered_stack(registered)

    assert viewer.star_overlay_button.isEnabled()
    assert viewer.star_overlay_button.isChecked()
    assert len(viewer._star_items) == len(positions)
    assert "Sterne gematcht" in viewer.frame_label.text()


def test_image_is_fitted_into_the_view(tmp_path):
    """Regressionsschutz: das Bild muss die Ansicht ausfuellen.

    Zuvor wurde nur beim allerersten Bild eingepasst — und das auch noch, waehrend der
    Viewer als verdeckte Seite eines QStackedWidget noch keine sinnvolle Groesse hatte.
    Das Ergebnis war ein winziger Fleck in der Bildmitte.
    """
    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    _write_star_field_fits(tmp_path / "a.fits", [(30.0, 40.0)], size=200)
    stack = load_frame_stack(tmp_path)

    # Bewusst ueber das echte Hauptfenster: dort liegt der Viewer als verdeckte Seite eines
    # QStackedWidget und hat vor dem ersten Anzeigen nur eine winzige Ersatzgroesse
    # (gemessen 98x28 px). Genau in diesem Zustand wurde frueher eingepasst — und danach
    # nie wieder, sodass das Bild dauerhaft als Fleck in der Mitte stehenblieb.
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()

    window._on_load_finished(stack)
    app.processEvents()  # das Einpassen laeuft verzoegert nach dem Layout

    view = window.image_viewer.view
    # Seitenverhaeltnistreues Einpassen fuellt genau eine Richtung vollstaendig aus; in der
    # anderen bleibt je nach Bildformat Rand. Geprueft wird die staerker gefuellte Richtung.
    shown = view.transform().mapRect(view.scene().itemsBoundingRect())
    viewport = view.viewport().rect()
    fill = max(shown.width() / viewport.width(), shown.height() / viewport.height())
    window.close()

    assert fill > 0.9, (
        f"Bild fuellt die Ansicht nur zu {fill:.0%} aus "
        f"({shown.width():.0f}x{shown.height():.0f} px in "
        f"{viewport.width()}x{viewport.height()} px)"
    )


def test_zooming_disables_auto_fit_and_button_restores_it(tmp_path):
    """Nach eigenem Zoom darf die Ansicht nicht ungefragt zurueckspringen — der
    Einpassen-Knopf muss aber zurueckfuehren."""
    _app = QApplication.instance() or QApplication([])  # noqa: F841
    _write_star_field_fits(tmp_path / "a.fits", [(30.0, 40.0)], size=200)
    viewer = ImageViewer()
    viewer.resize(800, 600)
    viewer.show()
    viewer.set_stack(load_frame_stack(tmp_path))
    viewer.view.fit_to_content()

    viewer.view.scale(4.0, 4.0)
    viewer.view._auto_fit = False
    zoomed = viewer.view.transform().m11()

    viewer.resize(900, 700)
    assert viewer.view.transform().m11() == zoomed, "Zoom des Nutzers darf nicht verworfen werden"

    viewer.view.reset_fit()
    assert viewer.view.transform().m11() != zoomed


def _write_sized_fits(path, height: int, width: int) -> None:
    header = fits.Header()
    header["DATE-OBS"] = "2026-01-01T00:00:00"
    fits.writeto(path, np.zeros((height, width), dtype=np.float32), header, overwrite=True)


def test_thumbnail_strip_moves_beside_portrait_images(tmp_path):
    """Bei Hochformataufnahmen ist die Hoehe die knappe Richtung. Ein waagerechter Streifen
    unter dem Bild wuerde genau dort Platz wegnehmen, waehrend seitlich Flaeche brachliegt."""
    app = QApplication.instance() or QApplication([])
    _write_sized_fits(tmp_path / "hoch.fits", height=192, width=108)

    viewer = ImageViewer()
    viewer.resize(800, 600)
    viewer.show()
    viewer.set_stack(load_frame_stack(tmp_path))
    app.processEvents()

    assert viewer.content_splitter.orientation() == Qt.Orientation.Horizontal


def test_thumbnail_strip_stays_below_landscape_images(tmp_path):
    app = QApplication.instance() or QApplication([])
    _write_sized_fits(tmp_path / "quer.fits", height=108, width=192)

    viewer = ImageViewer()
    viewer.resize(800, 600)
    viewer.show()
    viewer.set_stack(load_frame_stack(tmp_path))
    app.processEvents()

    assert viewer.content_splitter.orientation() == Qt.Orientation.Vertical


def test_image_area_gets_most_of_the_space(tmp_path):
    """Das Bild ist der Hauptinhalt: der Thumbnail-Streifen darf ihm nicht den Raum nehmen.
    Zuvor beanspruchte er ueber seinen Groessenhinweis fast die Haelfte."""
    app = QApplication.instance() or QApplication([])
    _write_sized_fits(tmp_path / "hoch.fits", height=192, width=108)

    viewer = ImageViewer()
    viewer.resize(1000, 700)
    viewer.show()
    viewer.set_stack(load_frame_stack(tmp_path))
    app.processEvents()

    image_size, strip_size = viewer.content_splitter.sizes()
    assert image_size > 3 * strip_size, (
        f"Bildbereich {image_size} px gegenueber Streifen {strip_size} px"
    )
