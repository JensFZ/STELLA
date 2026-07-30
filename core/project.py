from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core.detection import DetectionResult
from core.synthetic_tracking import VelocityVector

DEFAULT_DB_PATH = Path.home() / ".stella" / "projects.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    fits_folder TEXT NOT NULL,
    reference_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    speed_arcsec_per_min REAL NOT NULL,
    angle_deg REAL NOT NULL,
    position_row INTEGER NOT NULL,
    position_col INTEGER NOT NULL,
    snr REAL NOT NULL,
    peak_value REAL NOT NULL,
    confirmed INTEGER,
    thumbnail_shape TEXT NOT NULL,
    thumbnail_data BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL,
    UNIQUE(name, kind)
);
"""


@dataclass
class Project:
    id: int
    name: str
    fits_folder: str
    reference_index: int
    created_at: str
    updated_at: str


@dataclass
class SearchPreset:
    id: int
    name: str
    kind: str  # z.B. "search" oder "astrometry"
    params: dict


class ProjectStore:
    """SQLite-basierte Sitzungs-/Projektverwaltung (PLAN.md Phase 7)."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- Projekte -----------------------------------------------------------------

    def create_project(self, name: str, fits_folder: str, reference_index: int = 0) -> Project:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO projects (name, fits_folder, reference_index, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, fits_folder, reference_index, now, now),
        )
        self._conn.commit()
        return Project(
            id=cursor.lastrowid,
            name=name,
            fits_folder=fits_folder,
            reference_index=reference_index,
            created_at=now,
            updated_at=now,
        )

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT id, name, fits_folder, reference_index, created_at, updated_at "
            "FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [Project(*row) for row in rows]

    def get_project(self, project_id: int) -> Project:
        row = self._conn.execute(
            "SELECT id, name, fits_folder, reference_index, created_at, updated_at "
            "FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Projekt {project_id} nicht gefunden")
        return Project(*row)

    def delete_project(self, project_id: int) -> None:
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    def touch_project(self, project_id: int) -> None:
        self._conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), project_id),
        )
        self._conn.commit()

    # -- Kandidaten -----------------------------------------------------------------

    def save_detections(self, project_id: int, detections: list[DetectionResult]) -> None:
        """Ersetzt die gespeicherten Kandidaten (inkl. Bestätigungsstatus) eines Projekts."""
        self._conn.execute("DELETE FROM detections WHERE project_id = ?", (project_id,))
        for detection in detections:
            thumbnail = np.ascontiguousarray(detection.thumbnail, dtype=np.float64)
            self._conn.execute(
                "INSERT INTO detections (project_id, speed_arcsec_per_min, angle_deg, "
                "position_row, position_col, snr, peak_value, confirmed, thumbnail_shape, "
                "thumbnail_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    detection.vector.speed_arcsec_per_min,
                    detection.vector.angle_deg,
                    detection.position[0],
                    detection.position[1],
                    detection.snr,
                    detection.peak_value,
                    None if detection.confirmed is None else int(detection.confirmed),
                    json.dumps(list(thumbnail.shape)),
                    thumbnail.tobytes(),
                ),
            )
        self._conn.commit()
        self.touch_project(project_id)

    def load_detections(self, project_id: int) -> list[DetectionResult]:
        rows = self._conn.execute(
            "SELECT speed_arcsec_per_min, angle_deg, position_row, position_col, snr, "
            "peak_value, confirmed, thumbnail_shape, thumbnail_data FROM detections "
            "WHERE project_id = ? ORDER BY snr DESC",
            (project_id,),
        ).fetchall()

        detections = []
        for speed, angle, row_pos, col_pos, snr, peak_value, confirmed, shape_json, data in rows:
            shape = tuple(json.loads(shape_json))
            thumbnail = np.frombuffer(data, dtype=np.float64).reshape(shape)
            detections.append(
                DetectionResult(
                    vector=VelocityVector(speed_arcsec_per_min=speed, angle_deg=angle),
                    position=(row_pos, col_pos),
                    snr=snr,
                    peak_value=peak_value,
                    thumbnail=thumbnail,
                    confirmed=None if confirmed is None else bool(confirmed),
                )
            )
        return detections

    # -- Parameter-Presets -----------------------------------------------------------

    def save_preset(self, name: str, kind: str, params: dict) -> SearchPreset:
        self._conn.execute(
            "INSERT INTO presets (name, kind, params_json) VALUES (?, ?, ?) "
            "ON CONFLICT(name, kind) DO UPDATE SET params_json = excluded.params_json",
            (name, kind, json.dumps(params)),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id, name, kind, params_json FROM presets WHERE name = ? AND kind = ?",
            (name, kind),
        ).fetchone()
        return SearchPreset(id=row[0], name=row[1], kind=row[2], params=json.loads(row[3]))

    def list_presets(self, kind: str) -> list[SearchPreset]:
        rows = self._conn.execute(
            "SELECT id, name, kind, params_json FROM presets WHERE kind = ? ORDER BY name",
            (kind,),
        ).fetchall()
        return [
            SearchPreset(id=row[0], name=row[1], kind=row[2], params=json.loads(row[3]))
            for row in rows
        ]

    def delete_preset(self, preset_id: int) -> None:
        self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        self._conn.commit()

    def seed_presets(self, kind: str, presets: dict[str, dict]) -> None:
        """Legt vorgegebene Presets an, sofern noch kein Preset mit diesem Namen existiert.

        Bewusst ohne ON CONFLICT-Update wie bei save_preset(): ein Preset, das die
        Aufrufstelle hier einträgt, aber der Nutzer inzwischen angepasst oder gelöscht hat,
        darf dadurch nicht wieder überschrieben bzw. zurückgeholt werden.
        """
        for name, params in presets.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO presets (name, kind, params_json) VALUES (?, ?, ?)",
                (name, kind, json.dumps(params)),
            )
        self._conn.commit()
