from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.project import Project, ProjectStore


class OpenProjectDialog(QDialog):
    """Listet gespeicherte Projekte (Sitzungen) zur Auswahl auf."""

    def __init__(self, parent: QWidget | None, project_store: ProjectStore):
        super().__init__(parent)
        self.setWindowTitle("Projekt öffnen")
        self.resize(500, 300)

        self.list_widget = QListWidget(self)
        for project in project_store.list_projects():
            label = f"{project.name}  —  {project.fits_folder}  ({project.updated_at[:19]})"
            item = QListWidgetItem(label)
            item.setData(1, project)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addWidget(buttons)

    def selected_project(self) -> Project | None:
        item = self.list_widget.currentItem()
        return item.data(1) if item is not None else None
