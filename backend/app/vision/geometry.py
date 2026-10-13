"""Zone polygons in pixel space for a given processing resolution."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

ZONE_COLORS = {  # BGR
    "work_area": (120, 200, 60),
    "part_zone": (230, 160, 40),
    "trigger_zone": (60, 200, 230),
    "pick_zone": (200, 110, 230),
    "exclusion": (90, 90, 90),
    "stroke_zone": (60, 60, 230),
}


@dataclass
class ZonePoly:
    id: str
    name: str
    type: str
    station_id: int | None
    pts_norm: np.ndarray  # (N,2) float
    pts_px: np.ndarray = field(init=False)  # (N,2) int32
    bbox: tuple[int, int, int, int] = field(init=False)  # x, y, w, h
    mask_roi: np.ndarray = field(init=False)  # bool mask inside bbox
    centroid: tuple[float, float] = field(init=False)
    area_px: int = field(init=False)
    _cnt: np.ndarray = field(init=False)

    def build(self, w: int, h: int) -> "ZonePoly":
        pts = np.round(self.pts_norm * np.array([w - 1, h - 1])).astype(np.int32)
        self.pts_px = pts
        x, y, bw, bh = cv2.boundingRect(pts)
        bw, bh = max(bw, 1), max(bh, 1)
        self.bbox = (x, y, bw, bh)
        mask = np.zeros((bh, bw), np.uint8)
        cv2.fillPoly(mask, [pts - np.array([x, y])], 1)
        self.mask_roi = mask.astype(bool)
        self.area_px = int(self.mask_roi.sum()) or 1
        m = cv2.moments(pts.astype(np.float32))
        if abs(m["m00"]) > 1e-6:
            self.centroid = (m["m10"] / m["m00"], m["m01"] / m["m00"])
        else:
            self.centroid = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        self._cnt = pts.reshape(-1, 1, 2).astype(np.float32)
        return self

    def contains(self, p: tuple[float, float] | None) -> bool:
        if p is None:
            return False
        return cv2.pointPolygonTest(self._cnt, (float(p[0]), float(p[1])), False) >= 0

    def roi(self, img: np.ndarray) -> np.ndarray:
        x, y, w, h = self.bbox
        return img[y : y + h, x : x + w]

    def ratio(self, binary: np.ndarray) -> float:
        """Fraction of zone pixels that are non-zero in a binary image of frame size."""
        r = self.roi(binary)
        if r.shape[:2] != self.mask_roi.shape:
            return 0.0
        return float(np.count_nonzero(r[self.mask_roi])) / self.area_px


def build_zones(raw_zones: list[dict], default_station_id: int | None, w: int, h: int) -> list[ZonePoly]:
    zones: list[ZonePoly] = []
    for z in raw_zones or []:
        pts = np.asarray(z.get("points") or [], dtype=np.float32)
        if pts.ndim != 2 or len(pts) < 3:
            continue
        sid = z.get("station_id")
        zones.append(
            ZonePoly(
                id=str(z.get("id")),
                name=z.get("name") or z.get("type", "zone"),
                type=z.get("type", "work_area"),
                station_id=sid if sid is not None else default_station_id,
                pts_norm=np.clip(pts, 0, 1),
            ).build(w, h)
        )
    return zones


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def default_zones() -> list[dict]:
    """Starting zones for a new camera; the user adjusts them in the zone editor."""
    return [
        {"id": "work", "name": "Work area", "type": "work_area", "station_id": None,
         "points": [[0.15, 0.2], [0.85, 0.2], [0.85, 1.0], [0.15, 1.0]]},
        {"id": "part", "name": "Part fixture", "type": "part_zone", "station_id": None,
         "points": [[0.4, 0.45], [0.6, 0.45], [0.6, 0.7], [0.4, 0.7]]},
    ]
