from __future__ import annotations

import threading

import numpy as np
from sqlalchemy import select

from ..database import SessionLocal, session_scope
from .. import models

_lock = threading.Lock()


def add_heatmap(camera_id: int, day: str, cols: int, rows: int, grid: np.ndarray) -> None:
    with _lock, session_scope() as db:
        row = db.scalar(select(models.HeatmapDay).where(models.HeatmapDay.camera_id == camera_id, models.HeatmapDay.day == day))
        g = np.round(grid.astype(np.float64).reshape(-1), 2)
        if row is None or row.cols != cols or row.rows != rows:
            if row is not None:
                db.delete(row)
                db.flush()
            db.add(models.HeatmapDay(camera_id=camera_id, day=day, cols=cols, rows=rows, grid=g.tolist()))
        else:
            row.grid = np.round(np.asarray(row.grid, dtype=np.float64) + g, 2).tolist()


def get_heatmap(camera_id: int, days: list[str], cols: int, rows: int) -> np.ndarray:
    total = np.zeros(cols * rows, np.float64)
    with SessionLocal() as db:
        for r in db.scalars(select(models.HeatmapDay).where(models.HeatmapDay.camera_id == camera_id, models.HeatmapDay.day.in_(days))):
            if r.cols == cols and r.rows == rows:
                total += np.asarray(r.grid, dtype=np.float64)
    return total
