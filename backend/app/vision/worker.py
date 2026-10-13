"""One thread per camera: read frame -> track persons -> run analyzers -> publish live state / cycles."""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import cv2
import numpy as np

from ..config import settings
from ..hub import hub, live
from ..schemas import CameraConfig
from .analyzers import REGISTRY, Analyzer, CycleDraft, FrameContext
from .geometry import ZONE_COLORS, ZonePoly, build_zones, dist
from .recorder import Recorder
from .sources import make_source
from .trackers import SKELETON, KP_CONF, Person, make_tracker

log = logging.getLogger(__name__)


@dataclass
class StationMeta:
    id: int
    line_id: int
    name: str
    sequence: int
    target_cycle_sec: float
    expected_picks: int
    parts_added: list[str] = field(default_factory=list)


@dataclass
class LineMeta:
    id: int
    name: str
    takt_time_sec: float


class CameraContext:
    """Everything analyzers need to know about the camera they run on."""

    def __init__(self, worker: "CameraWorker", w: int, h: int) -> None:
        info = worker.info
        self.worker = worker
        self.camera_id: int = info["id"]
        self.line_id: int = info["line_id"]
        self.default_station_id: int | None = info.get("station_id")
        self.config: CameraConfig = worker.config
        self.stations: dict[int, StationMeta] = worker.stations
        self.width, self.height = w, h
        self.zones: list[ZonePoly] = [
            z for z in build_zones(info.get("zones") or [], self.default_station_id, w, h)
            if z.type == "exclusion" or z.station_id in self.stations
        ]
        self.default_m_per_px = self.config.meters_per_frame_width / max(1, w)
        self.reference: np.ndarray | None = None

        cyc = {z.station_id for z in self.zones if z.type in ("part_zone", "trigger_zone", "stroke_zone") and z.station_id is not None}
        if self.config.cycle_method == "activity":
            cyc |= {z.station_id for z in self.zones if z.type == "work_area" and z.station_id is not None}
        if not cyc and self.default_station_id in self.stations:
            cyc = {self.default_station_id}
        self.cycle_station_ids: list[int] = sorted(s for s in cyc if s is not None)
        others = {z.station_id for z in self.zones if z.type in ("work_area", "pick_zone") and z.station_id is not None}
        self.station_ids: list[int] = sorted(set(self.cycle_station_ids) | others)

    def zones_of(self, ztype: str, station_id: int | None = None) -> list[ZonePoly]:
        return [z for z in self.zones if z.type == ztype and (station_id is None or z.station_id == station_id)]

    def first_zone(self, ztype: str, station_id: int | None = None) -> ZonePoly | None:
        zs = self.zones_of(ztype, station_id)
        return zs[0] if zs else None

    # callbacks used by analyzers
    def reset_station(self, station_id: int, t: float) -> None:
        self.worker.reset_station(station_id, t)

    def set_cycle_start(self, station_id: int, t: float) -> None:
        self.worker.cycle_start[station_id] = t

    def complete_cycle(self, draft: CycleDraft) -> None:
        self.worker.complete_cycle(draft)


def _status_dict(**kw: Any) -> dict:
    base = {"online": False, "fps": 0.0, "last_frame_at": None, "error": None, "tracker": "none", "width": 0, "height": 0, "needs_reference": False}
    base.update(kw)
    return base


class CameraWorker(threading.Thread):
    def __init__(self, info: dict, stations: dict[int, StationMeta], line: LineMeta) -> None:
        super().__init__(daemon=True, name=f"camera-{info['id']}")
        self.info = info
        self.camera_id: int = info["id"]
        self.config = CameraConfig(**(info.get("config") or {}))
        self.stations = stations
        self.line = line
        self._stop_evt = threading.Event()
        self.lock = threading.Lock()
        self.status = _status_dict()
        self.viewers = 0
        self.jpeg: bytes | None = None
        self.jpeg_seq = 0
        self.latest_frame: np.ndarray | None = None
        self.cycle_start: dict[int, float] = {}
        self.cycle_memory: dict[int, dict] = {}  # rhythm / recent cycle times per station, kept across reconnects
        self._ref_request = False
        self._last_fc: FrameContext | None = None
        self.ctx: CameraContext | None = None
        self.analyzers: list[Analyzer] = []
        self.recorder: Recorder | None = None
        self._last_operator: dict[int, tuple[float, float]] = {}  # station -> where its operator stood last
        self.tracker: Any = None
        self.source: Any = None
        self._bg_sub = None
        self._excl_mask: np.ndarray | None = None
        self.is_synthetic = info["source_type"] == "simulated"
        self.ref_path = settings.references_dir / f"cam_{self.camera_id}.png"

    # ------------------------------------------------------------ control
    def stop(self) -> None:
        self._stop_evt.set()

    def request_reference(self) -> bool:
        if self.latest_frame is None:
            return False
        cv2.imwrite(str(self.ref_path), self.latest_frame)
        self._ref_request = True
        return True

    def update_meta(self, stations: dict[int, StationMeta], line: LineMeta) -> None:
        self.stations, self.line = stations, line
        if self.ctx is not None:
            self.ctx.stations = stations

    # ------------------------------------------------------------ helpers
    def _set_status(self, **kw: Any) -> None:
        was_online = self.status.get("online")
        self.status.update(kw)
        if kw.get("online") is not None and kw["online"] != was_online:
            hub.publish("camera_status", {"camera_id": self.camera_id, **self.status})
            if not kw["online"]:
                live.set_offline(self.camera_id)

    def _open_source(self) -> bool:
        station = self.stations.get(self.info.get("station_id")) if self.info.get("station_id") else None
        try:
            self.source = make_source(self.info, station)
            ok = self.source.open()
        except Exception as e:
            self.source = None
            self._set_status(online=False, error=str(e))
            return False
        if not ok:
            self.source = None
            self._set_status(online=False, error="cannot open video source")
            return False
        self.tracker = make_tracker(self.config.tracker, self.source)
        self._set_status(error=None, tracker=getattr(self.tracker, "name", "none"))
        return True

    def _setup_pipeline(self, w: int, h: int) -> None:
        for a in self.analyzers:  # reconnect / resolution change: keep accumulated data
            try:
                a.flush(force=True)
            except Exception:
                log.exception("flush failed")
        self.ctx = CameraContext(self, w, h)
        self._load_reference(w, h)
        if self.recorder is not None:
            self.recorder.close()
        self.recorder = Recorder(self.camera_id, self.config.process_fps) if self.config.record else None
        keys = [k for k in self.config.analyzers if k in REGISTRY]
        if "cycle_time" not in keys:
            keys.insert(0, "cycle_time")
        self.analyzers = sorted((REGISTRY[k](self.ctx) for k in keys), key=lambda a: a.order)
        for sid in self.ctx.cycle_station_ids:
            live.update(sid, camera_id=self.camera_id, state="waiting")
        self._bg_sub = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=40, detectShadows=False)
        excl = self.ctx.zones_of("exclusion")
        self._excl_mask = None
        if excl:  # conveyors, passages, neighbouring stations: ignore motion there
            self._excl_mask = np.full((h, w), 255, np.uint8)
            cv2.fillPoly(self._excl_mask, [z.pts_px for z in excl], 0)
        if hasattr(self.tracker, "anchor"):
            # motion tracker: assume the operator stands at the bottom edge of the work area (camera facing the bench)
            was = self.ctx.zones_of("work_area")
            if was:
                pts = np.vstack([z.pts_px for z in was])
                self.tracker.anchor = (float(pts[:, 0].min() + pts[:, 0].max()) / 2, float(pts[:, 1].max()))
            else:
                self.tracker.anchor = (w / 2, h - 1.0)

    def _load_reference(self, w: int, h: int) -> None:
        assert self.ctx is not None
        img = None
        if self.ref_path.exists():
            img = cv2.imread(str(self.ref_path))
        elif self.is_synthetic and self.source is not None:
            img = self.source.reference_frame()
            cv2.imwrite(str(self.ref_path), img)
        if img is not None:
            img = cv2.resize(img, (w, h)) if img.shape[1] != w or img.shape[0] != h else img
            self.ctx.reference = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        # with pose the cycles come from the operator's visits to the fixture, so no reference image is needed
        needs = (self.config.cycle_method == "part_presence" and self.ctx.reference is None and bool(self.ctx.zones_of("part_zone"))
                 and getattr(self.tracker, "name", "") != "pose")
        self.status["needs_reference"] = needs

    def recent_cycles(self, station_id: int) -> list[float]:
        """Recent cycle times of a station from the database when they are consistent (warms up cycle detection
        after a restart); inconsistent history (e.g. from an older detection method) is ignored."""
        try:
            from sqlalchemy import select

            from .. import models
            from ..database import SessionLocal

            with SessionLocal() as db:
                rows = list(db.scalars(select(models.Cycle.cycle_sec).where(
                    models.Cycle.station_id == station_id, models.Cycle.ended_at >= datetime.now() - timedelta(hours=3))
                    .order_by(models.Cycle.ended_at.desc()).limit(15)))
        except Exception as e:
            log.warning("could not read recent cycles (%s)", type(e).__name__)
            return []
        if len(rows) < 5:
            return []
        q1, med, q3 = np.percentile(rows, [25, 50, 75])
        return [float(r) for r in reversed(rows)] if med > 0 and (q3 - q1) / med <= 0.35 else []

    def reset_station(self, station_id: int, t: float) -> None:
        for a in self.analyzers:
            a.reset_station(station_id, t)

    def complete_cycle(self, draft: CycleDraft) -> None:
        for a in self.analyzers:
            a.contribute(draft)
        if not draft.has_movement:
            draft.work_sec = min(draft.processing_sec, draft.cycle_sec)
            draft.wait_sec = max(0.0, draft.cycle_sec - draft.work_sec)
        meta = self.stations.get(draft.station_id)
        if meta is None:
            return
        try:
            from ..services.cycles import persist_cycle

            persist_cycle(draft, self.camera_id, meta, self.line, source="simulated" if self.is_synthetic else "vision")
        except Exception:
            log.exception("failed to save cycle for station %s", draft.station_id)

    # ------------------------------------------------------------ per frame
    def _assign_persons(self, persons: list[Person], fc: FrameContext) -> None:
        assert self.ctx is not None
        ctx = self.ctx
        excl = ctx.zones_of("exclusion")
        if excl:
            persons = [p for p in persons if not any(z.contains(p.body) for z in excl)]
        fc.persons = persons
        diag = float(np.hypot(ctx.width, ctx.height))

        def stand(p: Person) -> tuple[float, float]:
            """Where the person stands: feet (bottom of the box) when visible, else the shoulders.
            Hands are not used - a colleague next to the station can reach into it."""
            if p.bbox is not None and p.bbox[3] < 0.97 * ctx.height:
                return ((p.bbox[0] + p.bbox[2]) / 2, p.bbox[3])
            return p.body

        def size(p: Person) -> float:
            return (p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1]) if p.bbox is not None else 0.0

        for sid in ctx.station_ids:
            was = ctx.zones_of("work_area", sid)
            if was:
                cands = [p for p in persons if any(z.contains(stand(p)) for z in was)]
                centre = was[0].centroid
            else:
                cands = list(persons)
                ref = ctx.first_zone("part_zone", sid) or ctx.first_zone("trigger_zone", sid)
                centre = ref.centroid if ref else None
            best = None
            last = self._last_operator.get(sid)
            if last is not None and persons:
                # keep following the same person, also when they walk out of the work area (no jumping between people)
                near = min(persons, key=lambda p: dist(stand(p), last))
                if dist(stand(near), last) <= 0.2 * diag:
                    best = near
            if best is None and cands:  # (re)acquire the operator inside the work area
                best = min(cands, key=lambda p: dist(stand(p), centre)) if centre is not None else max(cands, key=size)
            if best is not None:
                self._last_operator[sid] = stand(best)
            fc.station_person[sid] = best

    def _process(self, frame: np.ndarray, now: float, dt: float) -> None:
        assert self.ctx is not None
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        fg_cache: dict[str, np.ndarray | None] = {}
        need_motion = self.config.cycle_method == "activity" or getattr(self.tracker, "name", "") == "motion" or self.ctx.reference is None

        # keep the background model warm when motion is needed, so it is ready on demand
        if need_motion and self._bg_sub is not None:
            small = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2))
            m = self._bg_sub.apply(small)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            m = cv2.dilate(m, np.ones((5, 5), np.uint8))
            m = cv2.resize(m, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
            if self._excl_mask is not None and self._excl_mask.shape == m.shape:
                m = cv2.bitwise_and(m, self._excl_mask)
            fg_cache["fg"] = m

        def fg_mask() -> np.ndarray | None:
            return fg_cache.get("fg")

        fc = FrameContext(t=now, dt=dt, frame=frame, gray=gray, fg_mask=fg_mask)
        try:
            persons = self.tracker.detect(fc) if self.tracker is not None else []
        except Exception as e:
            log.warning("tracker failed on camera %s: %s", self.camera_id, e)
            persons = []
        self._assign_persons(persons, fc)
        if self.recorder is not None:
            main_sid = self.info.get("station_id") or (self.ctx.cycle_station_ids[0] if self.ctx.cycle_station_ids else None)
            try:
                self.recorder.write(now, frame, fc.persons, fc.station_person.get(main_sid) if main_sid else None)
            except Exception:
                log.exception("recording failed on camera %s", self.camera_id)
        for a in self.analyzers:
            a.process(fc)
        self._last_fc = fc
        self._publish_live(fc)

    def _publish_live(self, fc: FrameContext) -> None:
        assert self.ctx is not None
        mov = next((a for a in self.analyzers if a.key == "movement"), None)
        for sid in self.ctx.cycle_station_ids:
            part = fc.part_present.get(sid)
            person = fc.station_person.get(sid)
            flags = mov.station_flags(sid) if mov else {}
            if part is False:
                state = "waiting"
            elif person is None or flags.get("idle") or flags.get("away"):
                state = "idle"
            else:
                state = "working"
            live.update(
                sid,
                camera_id=self.camera_id,
                state=state,
                operator_present=person is not None,
                part_present=bool(part),
                cycle_start_ts=self.cycle_start.get(sid),
            )

    # ------------------------------------------------------------ overlay
    def _draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        img = frame.copy()
        ctx, fc = self.ctx, self._last_fc
        if ctx is None:
            return img
        over = img.copy()
        for z in ctx.zones:
            color = ZONE_COLORS.get(z.type, (200, 200, 200))
            if z.type == "part_zone" and fc is not None and fc.part_present.get(z.station_id):
                cv2.fillPoly(over, [z.pts_px], (80, 220, 80))
            elif z.type in ("exclusion", "pick_zone"):
                cv2.fillPoly(over, [z.pts_px], color)
        cv2.addWeighted(over, 0.25, img, 0.75, 0, img)
        for z in ctx.zones:
            color = ZONE_COLORS.get(z.type, (200, 200, 200))
            cv2.polylines(img, [z.pts_px], True, color, 1, cv2.LINE_AA)
            if z.type in ("work_area", "pick_zone"):
                x, y, _, _ = z.bbox
                cv2.putText(img, z.name[:18], (x + 3, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)
        if fc is not None:
            for p in fc.persons:
                if p.keypoints is not None:
                    kp = p.keypoints
                    for a, b in SKELETON:
                        if kp[a, 2] >= KP_CONF and kp[b, 2] >= KP_CONF:
                            cv2.line(img, (int(kp[a, 0]), int(kp[a, 1])), (int(kp[b, 0]), int(kp[b, 1])), (255, 180, 60), 2, cv2.LINE_AA)
                elif p.bbox is None and self.tracker is not None and self.tracker.name == "motion":
                    for w in p.wrists:
                        if w is not None:
                            cv2.circle(img, (int(w[0]), int(w[1])), 10, (255, 180, 60), 1, cv2.LINE_AA)
            for a in self.analyzers:
                a.draw(img, fc)
        # station info boxes
        now = time.time()
        y = 8
        for sid in ctx.cycle_station_ids:
            meta = self.stations.get(sid)
            st = live.get(sid)
            if meta is None or st is None:
                continue
            elapsed = st["cycle_elapsed_sec"]
            over_target = elapsed is not None and elapsed > meta.target_cycle_sec
            col = {"working": (90, 210, 90), "waiting": (40, 190, 240), "idle": (40, 140, 255)}.get(st["state"], (160, 160, 160))
            lines = [
                f"Step {meta.sequence}: {meta.name}"[:34],
                f"{st['state'].upper()}  {elapsed or 0:5.1f}s / {meta.target_cycle_sec:.0f}s",
                f"last {st['last_cycle_sec'] or 0:.1f}s  count {st['count_today']}",
            ]
            bw, bh = 210, 54
            x0 = img.shape[1] - bw - 8
            sub = img[y : y + bh, x0 : x0 + bw]
            if sub.shape[0] == bh:
                img[y : y + bh, x0 : x0 + bw] = (sub * 0.35).astype(np.uint8)
            cv2.rectangle(img, (x0, y), (x0 + bw, y + bh), col, 1)
            for i, t in enumerate(lines):
                c = (60, 60, 255) if (i == 1 and over_target) else ((230, 230, 230) if i != 1 else col)
                cv2.putText(img, t, (x0 + 6, y + 15 + i * 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1, cv2.LINE_AA)
            y += bh + 6
        txt = f"{self.info['name']}  {self.status.get('fps', 0):.1f} fps  {self.status.get('tracker')}  {datetime.fromtimestamp(now):%H:%M:%S}"
        cv2.putText(img, txt, (8, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, txt, (8, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (235, 235, 235), 1, cv2.LINE_AA)
        if self.status.get("needs_reference"):
            cv2.putText(img, "Capture empty reference for part detection", (8, img.shape[0] - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1, cv2.LINE_AA)
        return img

    def render_jpeg(self, overlay: bool = True) -> bytes | None:
        frame = self.latest_frame
        if frame is None:
            return None
        img = self._draw_overlay(frame) if overlay else frame
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------ main loop
    def run(self) -> None:
        # reconnects are spaced out (3 s doubling to 60 s, with jitter): a burst of connection attempts from
        # many cameras looks like an attack to some factory routers / cameras, which then block this PC
        backoff = 3.0
        fails = 0
        next_proc = next_stream = 0.0
        last_proc = None
        fps_ema = 0.0
        frame_size: tuple[int, int] | None = None
        self._stop_evt.wait(getattr(self, "initial_delay", 0.0))
        while not self._stop_evt.is_set():
            try:
                if self.source is None:
                    if not self._open_source():
                        self._stop_evt.wait(backoff * random.uniform(0.7, 1.3))
                        backoff = min(backoff * 2, 60.0)
                        continue
                    backoff, fails = 3.0, 0
                    frame_size = None
                elif getattr(self.source, "wants_reopen", False):
                    log.info("camera %s: trying the sub stream again", self.camera_id)
                    self.source.close()
                    self.source = None
                    continue

                proc_iv = 1.0 / max(0.5, self.config.process_fps)
                stream_iv = 1.0 / max(1.0, settings.stream_fps)
                want_stream = self.viewers > 0
                target = min(next_proc, next_stream) if want_stream else next_proc
                delay = target - time.time()
                if delay > 0:
                    self._stop_evt.wait(min(delay, 0.5))
                    continue

                ok, frame = self.source.read()
                if not ok or frame is None:
                    fails += 1
                    if fails > 50:
                        self._set_status(online=False, error="no frames from camera (reconnecting)")
                        try:
                            self.source.close()
                        finally:
                            self.source = None
                    else:
                        self._stop_evt.wait(0.1)
                    continue
                fails = 0
                pw = settings.process_width
                aspect = getattr(self.source, "target_aspect", None) or frame.shape[1] / frame.shape[0]
                ph = int(round(pw / aspect))
                if frame.shape[1] != pw or frame.shape[0] != ph:
                    frame = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)
                h, w = frame.shape[:2]
                if frame_size != (w, h):
                    frame_size = (w, h)
                    self._setup_pipeline(w, h)
                    self.status.update(width=w, height=h)
                if self._ref_request:
                    self._ref_request = False
                    self._load_reference(w, h)
                self.latest_frame = frame
                now = time.time()
                if now >= next_proc:
                    dt = 0.0 if last_proc is None else min(2.0, now - last_proc)
                    if last_proc is not None and dt > 0:
                        fps_ema = (1 / dt) if fps_ema == 0 else 0.9 * fps_ema + 0.1 * (1 / dt)
                    last_proc = now
                    try:
                        self._process(frame, now, dt)
                    except Exception:
                        log.exception("processing error on camera %s", self.camera_id)
                    next_proc = now + proc_iv
                    self._set_status(online=True, fps=round(fps_ema, 1), last_frame_at=datetime.now())
                if want_stream and now >= next_stream:
                    jpg = self.render_jpeg(True)
                    if jpg:
                        self.jpeg, self.jpeg_seq = jpg, self.jpeg_seq + 1
                    next_stream = now + stream_iv
            except Exception:  # e.g. MemoryError on a huge frame: keep the camera alive, retry
                log.exception("camera %s: loop error", self.camera_id)
                self._stop_evt.wait(1.0)

        # shutdown
        for a in self.analyzers:
            try:
                a.flush(force=True)
            except Exception:
                pass
        if self.recorder is not None:
            self.recorder.close()
        if self.source is not None:
            self.source.close()
        live.release_camera(self.camera_id)
        self.status.update(online=False, fps=0.0)
