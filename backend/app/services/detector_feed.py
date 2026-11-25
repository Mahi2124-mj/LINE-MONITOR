"""Live cycle count from the validated step detectors (tools/reports/station_breakup.py).

The generic live counter ("the operator's hands come to the part") merges cycles where one person runs several machines
on one camera (YRA). The step detectors were checked frame by frame against the video, so for the steps they cover
they own the cycle count: every few minutes they run on the last minutes of the recording (one low-priority process per
camera) and their cycles are written to the database (source "detector"). The generic counter keeps the live state and
timer of those steps, but its cycles are not stored, and its older cycles of those steps are left out of the analytics.

A block of ~10 minutes in which a step's count disagrees with its partner step on the same camera (a detector that lost
its cue, e.g. a new layout) is not written: one wrong step must not become a false bottleneck. Cycles appear with a delay of ~2-7 minutes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import statistics as stat
import subprocess
import sys
import time
from datetime import datetime

from sqlalchemy import select

from .. import models
from ..config import BACKEND_DIR, settings
from ..database import SessionLocal, session_scope
from ..hub import live

log = logging.getLogger(__name__)

FEED_KEYS = ("yur", "yhs", "yxl", "yg1", "yg2", "ylr", "ysr", "ysf", "yml", "ymm", "yfi", "yjc", "ytp")
TOOL = BACKEND_DIR / "tools" / "reports" / "detector_feed.py"
EVERY_SEC = 300      # one run per camera every 5 minutes
LAG_SEC = 90         # the detectors confirm a cycle only some seconds after it ended
CONTEXT_SEC = 120    # recording read before the last stored cycle, so the detectors start in a known state
CARRY_SEC = 600      # a cycle still going on at the end of a run is stored by the next run (if it is not longer than this)
CHUNK_SEC = 1800     # catching up (server start / backfill since the shift start) in 30-minute pieces
CHUNKS_PER_RUN = 12
PARALLEL = 4         # cameras processed at the same time (~0.2-0.5 GB each)
BACKFILL_SEC = 12 * 3600  # the recordings are kept 12 h
TIMEOUT_SEC = 900
BLOCK_SEC = 600      # the partner check compares counts per ~10 minutes
# steps a detector covers only for some parts: (key, station) -> the cycle flag that must not be False. YRA step 11 Pop
# Rivet Gun is used for inner rails only; outer rails go from step 10 straight to Final Inspection (step 12).
USED_IF = {("yfi", 11): "rivet"}
STOP_SEC = 180       # no cycle for this long = a stoppage alert
# the steps whose count each step must agree with (same person's loop, or the person who hands the part over). A step is
# kept in a block when it agrees with at least one of them or with the whole line (the median of all steps: there are no
# buffers, so every step makes about the same parts): one weak detector cannot drag a correct one down with it.
PARTNERS = {"yur": ("yhs", "yxl"), "yhs": ("yur", "yxl"), "yxl": ("yhs", "yur"), "yg1": ("yg2",), "yg2": ("yg1",),
            "ylr": ("ysr", "ysf"), "ysr": ("ylr", "ysf"), "ysf": ("ysr", "ylr"), "yml": ("ymm",), "ymm": ("yml", "yfi"),
            "yfi": ("ymm", "yml"),
            # YWD SS: every taped rail goes to YJC-SS-09 through the front tray
            "yjc": ("ytp",), "ytp": ("yjc",)}
PARALLEL_KEYS = {"yg1": 2, "yg2": 2}  # copies of one machine: each makes half the parts


ELEMENT_META = settings.data_dir / "detector_elements.json"
# per step: the times its count is incomplete (no video: camera offline, server restart; or a block the partner check
# left out). The parts count leaves those people out there (analytics.parts_counter).
MISSING = settings.data_dir / "detector_missing.json"
FRAME_GAP = 2.0           # recorded frames further apart than this: video missing
MISSING_KEEP = 35 * 86400
_FRAME_T = re.compile(rb'"t":([0-9.]+)')
_missing_cache: tuple[float, dict[int, list[tuple[float, float]]]] = (0.0, {})


def video_holes(cam_id: int, a: float, b: float) -> list[tuple[float, float]]:
    """the parts of [a, b] the camera's recording has no frames for"""
    d = settings.recordings_dir / f"cam_{cam_id}"
    lo = datetime.fromtimestamp(a - 300).strftime("%Y%m%d_%H%M%S")
    hi = datetime.fromtimestamp(b).strftime("%Y%m%d_%H%M%S")
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith(".jsonl") and lo <= f[:-6] <= hi)
    except OSError:
        return [(a, b)]
    ts: list[float] = []
    for f in names:
        try:
            ts += [t for t in map(float, _FRAME_T.findall((d / f).read_bytes())) if a <= t <= b]
        except (OSError, ValueError):
            continue
    ts.sort()
    holes, prev = [], a
    for t in ts + [b]:
        if t - prev > FRAME_GAP:
            holes.append((prev, t))
        prev = max(prev, t)
    return holes


def missing_times() -> dict[int, list[tuple[float, float]]]:
    """station id -> the times its count is incomplete"""
    global _missing_cache
    try:
        mt = MISSING.stat().st_mtime
    except OSError:
        return {}
    if mt != _missing_cache[0]:
        try:
            raw = json.loads(MISSING.read_text(encoding="utf-8"))
            _missing_cache = (mt, {int(k): [(a, b) for a, b in v] for k, v in raw.items()})
        except (OSError, ValueError):
            return _missing_cache[1]
    return _missing_cache[1]


def add_missing(add: dict[int, list[tuple[float, float]]]) -> None:
    if not any(add.values()):
        return
    cur ={k: list(v) for k, v in missing_times().items()}
    floor = time.time() - MISSING_KEEP
    for sid, iv in add.items():
        merged: list[list[float]] = []
        for a, b in sorted([*cur.get(sid, []), *iv]):
            if b < floor:
                continue
            if merged and a <= merged[-1][1] + 1.0:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        cur[sid] = [(round(a, 1), round(b, 1)) for a, b in merged]
    tmp = MISSING.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(k): v for k, v in cur.items() if v}), encoding="utf-8")
    os.replace(tmp, MISSING)


def save_element_meta(meta: dict) -> None:
    """what each detector element is: {key: {code: [label, kind]}}, kind = work / walk / wait / machine"""
    try:
        cur = json.loads(ELEMENT_META.read_text(encoding="utf-8")) if ELEMENT_META.exists() else {}
    except (OSError, ValueError):
        cur = {}
    if any(cur.get(k) != v for k, v in meta.items()):
        cur.update(meta)
        ELEMENT_META.write_text(json.dumps(cur, indent=1), encoding="utf-8")


def element_meta() -> dict:
    try:
        return json.loads(ELEMENT_META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _jobs() -> dict[str, dict]:
    from .report_engine import STATION_JOBS

    return {k: v for k, v in STATION_JOBS.items() if k in FEED_KEYS and v.get("stations")}


class DetectorFeed:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.wm: dict[str, float] = {}          # per key: the recording up to here is processed
        self.kept: dict[str, float] = {}        # per key: end of the newest cycle found (the next run keeps cycles from here)
        self.owned: set[int] = set()            # station ids whose cycles come from the detectors
        self.broken: dict[str, float] = {}      # key -> time it reported "no such detector" (retried after an hour)
        self.last: dict[str, dict] = {}         # per key: last run result (for the status endpoint)
        self.last_end: dict[str, float] = {}    # per key: end of the newest stored cycle
        self.stop_alerted: set[str] = set()     # operators / lines whose current stop was already alerted

    def owns(self, station_id: int) -> bool:
        return station_id in self.owned

    def prepare(self) -> None:
        """at server start, before today's counts are loaded: which steps the detectors own"""
        if settings.detector_feed:
            self._refresh_owned()

    async def start(self) -> None:
        if not settings.detector_feed:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def status(self) -> dict:
        return {"enabled": settings.detector_feed, "owned_stations": sorted(self.owned), "last": self.last,
                "watermark": {k: datetime.fromtimestamp(v).isoformat(timespec="seconds") for k, v in self.wm.items()}}

    # ---------------------------------------------------------------- which steps the detectors own
    def _active_jobs(self) -> dict[str, dict]:
        with SessionLocal() as db:
            active = {line.id for line in db.scalars(select(models.Line)) if line.is_active}
            st_line = {s.id: s.line_id for s in db.scalars(select(models.Station)) if s.is_active}
            recorded = {c.id for c in db.scalars(select(models.Camera)) if c.enabled and (c.config or {}).get("record")}
        now = time.time()
        return {k: v for k, v in _jobs().items()
                if all(c in recorded for c in v["cams"]) and all(st_line.get(s) in active for s in v["stations"])
                and now - self.broken.get(k, 0) > 3600}

    def _refresh_owned(self) -> None:
        self.owned = {s for v in self._active_jobs().values() for s in v["stations"]}

    # ---------------------------------------------------------------- loop
    async def _loop(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                await asyncio.to_thread(self._refresh_owned)
                await self._run_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("detector feed error")
            await asyncio.sleep(EVERY_SEC)

    def _start_mark(self, key: str, stations: tuple) -> float:
        """where a key continues: after its last stored cycle, else from the shift start (at most BACKFILL_SEC back)"""
        with SessionLocal() as db:
            # the newest cycle of any of its steps (a step used only for some parts may have none for a while)
            last = db.scalar(select(models.Cycle.ended_at).where(models.Cycle.station_id.in_(stations), models.Cycle.source == "detector")
                             .order_by(models.Cycle.ended_at.desc()).limit(1))
            line = db.get(models.Line, db.get(models.Station, stations[0]).line_id)
            h, m = (int(x) for x in line.shift_start.split(":"))
        now = time.time()
        floor = now - BACKFILL_SEC
        if last is not None and last.timestamp() > floor:
            return last.timestamp() + 0.5
        shift = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
        return max(floor, shift if shift < now else now - 900)

    def _keep_from(self, key: str) -> float:
        """cycles of a key are kept from here: the end of its newest cycle found, at most CARRY_SEC before the processed
        recording (a longer gap is a stop, not a cycle going on)"""
        return max(self.kept.get(key, self.wm[key]), self.wm[key] - CARRY_SEC)

    async def _run_all(self) -> None:
        jobs = self._active_jobs()
        by_cam: dict[int, list[str]] = {}
        for k, v in jobs.items():
            if k not in self.wm:
                self.wm[k] = await asyncio.to_thread(self._start_mark, k, v["stations"])
                self.kept[k] = self.wm[k]
            by_cam.setdefault(v["cams"][0], []).append(k)
        sem = asyncio.Semaphore(PARALLEL)
        for _ in range(CHUNKS_PER_RUN):
            t_end = time.time() - LAG_SEC
            results: dict[str, list[dict]] = {}
            raw: dict[str, list[dict]] = {}  # every cycle the tool found in the window (also before a key's watermark)
            windows: dict[str, tuple[float, float]] = {}
            behind = False

            async def one(keys: list[str]) -> None:
                nonlocal behind
                w0 = min(self.wm[k] for k in keys)
                if t_end - w0 < 60:
                    return
                w1 = min(t_end, w0 + CHUNK_SEC)
                behind |= w1 < t_end
                async with sem:
                    got = await self._run_tool(keys, min(self._keep_from(k) for k in keys) - CONTEXT_SEC, w1)
                for k in keys:
                    if k in got:
                        raw[k] = got[k]
                        # from the end of the newest cycle found before: the cycle that went past the last run's end
                        # (it ends with the next take) is stored now, once (the one before it starts a cycle earlier)
                        results[k] = [c for c in got[k] if c["start"] >= self._keep_from(k) - 2.0 and c["end"] <= w1]
                        windows[k] = (self.wm[k], w1)

            await asyncio.gather(*(one(keys) for keys in by_cam.values()))
            if not results:
                return
            bad = self._disagreeing(raw, windows)
            await asyncio.to_thread(self._store, results, windows, bad, jobs)
            if not behind:
                return

    async def _run_tool(self, keys: list[str], t0: float, t1: float) -> dict[str, list[dict]]:
        env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONIOENCODING="utf-8")
        flags = 0x00004000 | 0x08000000 if sys.platform == "win32" else 0  # below-normal priority, no window
        cmd = [sys.executable, str(TOOL), f"{t0:.3f}", f"{t1:.3f}", *keys]
        started = time.time()
        try:
            proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(BACKEND_DIR), env=env, creationflags=flags,
                                           capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SEC)
            res = json.loads(proc.stdout or "{}")
        except (subprocess.TimeoutExpired, ValueError) as e:
            log.warning("detector feed %s: %s", keys, e)
            for k in keys:
                self.last[k] = {"ok": False, "message": str(e)[:200], "at": datetime.now().isoformat(timespec="seconds")}
            return {}
        for k, msg in (res.get("errors") or {}).items():
            log.warning("detector feed %s: %s", k, msg)
            self.last[k] = {"ok": False, "message": msg[:200], "at": datetime.now().isoformat(timespec="seconds")}
            if msg == "no such detector":  # not installed: its steps go back to the generic counter
                self.broken[k] = time.time()
        if res.get("errors"):
            self._refresh_owned()
        if res.get("meta"):
            save_element_meta(res["meta"])
        log.info("detector feed %s: %.0fs", ",".join(keys), time.time() - started)
        return res.get("cycles") or {}

    def _disagreeing(self, results: dict[str, list[dict]], windows: dict[str, tuple[float, float]]) -> dict[str, list[tuple[float, float]]]:
        """per key, the ~10-minute blocks in which its count agrees with none of its partner steps and not with the line
        (the median of all steps): those cycles are not stored, because its detector lost its cue there. A few "cycles"
        while everything else made none (the line stands still: lamps, reflections, someone passing) are left out too.
        Counted on all cycles found in the window, so a key that catches up alone is still compared."""

        def agree(x: float, y: float) -> bool:
            return abs(x - y) <= max(3, 0.2 * max(x, y)) and (x > 0) == (y > 0)

        out: dict[str, list[tuple[float, float]]] = {}
        for k, refs in PARTNERS.items():
            refs = tuple(r for r in refs if r in results)
            if k not in results or not refs:
                continue
            w0, w1 = windows[k]  # the partners' raw cycles cover this whole window
            n = max(1, round((w1 - w0) / BLOCK_SEC))
            for i in range(n):
                b0, b1 = w0 + (w1 - w0) * i / n, w0 + (w1 - w0) * (i + 1) / n
                count = lambda key: sum(1 for c in results[key] if b0 <= c["end"] < b1) * PARALLEL_KEYS.get(key, 1)  # noqa: E731
                a = count(k)
                line = [count(x) for x in results if x != k]
                med = stat.median(line) if len(line) >= 4 else None
                if not any(agree(a, count(r)) for r in refs) and not (med is not None and agree(a, med)):
                    out.setdefault(k, []).append((b0, b1))
        return out

    def _store(self, results: dict[str, list[dict]], windows: dict[str, tuple[float, float]], bad: dict[str, list[tuple[float, float]]],
               jobs: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        hm = lambda t: datetime.fromtimestamp(t).strftime("%H:%M")  # noqa: E731
        removed: dict[str, list[tuple[float, float]]] = {}  # per key: the blocks whose cycles were left out
        with session_scope() as db:
            sts = {s.id: s for s in db.scalars(select(models.Station))}
            for k, cyc in results.items():
                w0, w1 = windows[k]
                self.wm[k] = max(self.wm[k], w1)  # never back: a key caught up already keeps its place
                if cyc:
                    self.kept[k] = max(self.kept.get(k, 0.0), max(c["end"] for c in cyc))
                skipped = bad.get(k, [])
                if skipped:
                    removed[k] = [(b0, b1) for b0, b1 in skipped if any(b0 <= c["end"] < b1 for c in cyc)]
                    keep = [c for c in cyc if not any(b0 <= c["end"] < b1 for b0, b1 in skipped)]
                    log.warning("detector feed %s: %d cycles left out (%s), count agrees with neither %s nor the line", k, len(cyc) - len(keep),
                                ", ".join(f"{hm(b0)}-{hm(b1)}" for b0, b1 in skipped), "/".join(PARTNERS[k]))
                    cyc = keep
                for sid in jobs[k]["stations"]:
                    s = sts.get(sid)
                    if s is None:
                        continue
                    flag = USED_IF.get((k, sid))
                    for c in cyc:
                        if flag and c.get(flag) is False:  # this part did not go through this step
                            continue
                        db.add(models.Cycle(
                            station_id=sid, line_id=s.line_id, camera_id=jobs[k]["cams"][0],
                            started_at=datetime.fromtimestamp(c["start"]), ended_at=datetime.fromtimestamp(c["end"]),
                            cycle_sec=c["sec"], work_sec=c["work"], motion_waste_sec=c["motion"], wait_sec=c["wait"],
                            source="detector", over_target=(c["work"] + c["motion"]) > s.target_cycle_sec,
                            elements={"key": k, "el": c["el"], **({"seg": c["seg"]} if c.get("seg") else {})} if c.get("el") else None,
                        ))
                        live.record_cycle(sid, c["sec"], c["end"], timer=False)
                self.last[k] = {"ok": True, "at": now, "cycles": len(cyc),
                                "window": [datetime.fromtimestamp(w0).strftime("%H:%M:%S"), datetime.fromtimestamp(w1).strftime("%H:%M:%S")],
                                **({"left_out": [f"{hm(b0)}-{hm(b1)}" for b0, b1 in skipped]} if skipped else {})}
                results[k] = cyc
        self._note_missing(windows, removed, jobs)
        self._stoppages(results, windows, bad, jobs)

    def _note_missing(self, windows: dict[str, tuple[float, float]], removed: dict[str, list[tuple[float, float]]], jobs: dict) -> None:
        """the times of this round each step's count is incomplete: no video, or cycles left out by the partner check"""
        by_cam: dict[int, list[str]] = {}
        for k in windows:
            by_cam.setdefault(jobs[k]["cams"][0], []).append(k)
        add: dict[int, list[tuple[float, float]]] = {}
        for cam, keys in by_cam.items():
            a, b = min(windows[k][0] for k in keys), max(windows[k][1] for k in keys)
            holes = video_holes(cam, a, b)
            for k in keys:
                w0, w1 = windows[k]
                iv = [(max(x, w0), min(y, w1)) for x, y in holes if y > w0 and x < w1] + removed.get(k, [])
                for sid in jobs[k]["stations"]:
                    add.setdefault(sid, []).extend(iv)
        try:
            add_missing(add)
        except OSError:
            log.exception("detector feed: missing times not saved")

    def _stoppages(self, results: dict[str, list[dict]], windows: dict[str, tuple[float, float]], bad: dict[str, list[tuple[float, float]]],
                   jobs: dict) -> None:
        """Stoppage alerts of the steps the detectors count (their live timer comes from the generic counter, which
        misses cycles): per person, no cycle for STOP_SEC; one alert per stop. When every person of the line stops
        (a break, a line stop) one alert for the line. Only time inside the line's planned slots counts (nights and
        non-working days are no stops), and not the time without video or with cycles left out by the partner check."""
        from .alerts import create_alert
        from .analytics import slots_between

        hm = lambda t: datetime.fromtimestamp(t).strftime("%H:%M")  # noqa: E731
        with SessionLocal() as db:
            sts = {s.id: s for s in db.scalars(select(models.Station))}
            lines = {ln.id: ln for ln in db.scalars(select(models.Line))}

        def planned(line_id: int, a: float, b: float) -> tuple[float, float]:
            """seconds of [a, b] inside the line's planned slots, and when the first of them begins"""
            ln = lines.get(line_id)
            if ln is None or not ln.slot_plan:
                return b - a, a
            A, Bt = datetime.fromtimestamp(a), datetime.fromtimestamp(b)
            parts = [(max(ws, A), min(we, Bt)) for ws, we, _, _ in slots_between(ln, A, Bt) if min(we, Bt) > max(ws, A)]
            if not parts:
                return 0.0, a
            return sum((y - x).total_seconds() for x, y in parts), min(x for x, _ in parts).timestamp()
        # one representative key per person (his steps are one loop): the one with most cycles in this round
        people: dict[tuple[int, str], str] = {}
        for k in results:
            s = sts.get(jobs[k]["stations"][0])
            if s is None:
                continue
            g = (s.line_id, s.operator_name.strip() or f"step {s.sequence}")
            if g not in people or len(results[k]) > len(results[people[g]]):
                people[g] = k
        stopped: dict[tuple[int, str], float] = {}
        recent = time.time() - 1200  # while catching up on older recording, stops that ended long ago are not alerted
        for g, k in people.items():
            cyc = sorted(c["end"] for c in results[k])
            prev = self.last_end.get(k)
            if cyc:
                self.last_end[k] = cyc[-1]
            ends = ([prev] if prev else []) + cyc
            w1 = windows[k][1]
            gaps = [*bad.get(k, []), *missing_times().get(jobs[k]["stations"][0], [])]

            def stop_sec(a: float, b: float) -> tuple[float, float]:
                """planned seconds of [a, b] with video and counted cycles, and when the planned part begins"""
                sec, a0 = planned(g[0], a, b)
                return sec - sum(max(0.0, min(y, b) - max(x, a)) for x, y in gaps), a0
            # a stop already alerted while it went on is not alerted again when it ends
            was_alerted = f"{g[0]}:{g[1]}" in self.stop_alerted or f"line:{g[0]}" in self.stop_alerted
            if cyc:
                self.stop_alerted.discard(f"{g[0]}:{g[1]}")
            # a stop that ended inside this round
            for a, b in zip(ends, ends[1:]):
                if b - a > STOP_SEC and b > recent and not (a == prev and was_alerted):
                    sec, a0 = stop_sec(a, b)
                    if sec <= STOP_SEC:
                        continue
                    s = sts[jobs[k]["stations"][0]]
                    create_alert("stoppage", "warning", f"{g[1]} (step {s.sequence} {s.name}): stopped {hm(a0)}-{hm(b)} ({sec / 60:.0f} min)",
                                 line_id=g[0], station_id=s.id, dedupe_min=60)
            # a stop still going on at the end of the round
            last = ends[-1] if ends else None
            if last and w1 - last > STOP_SEC and w1 > recent:
                sec, a0 = stop_sec(last, w1)
                if sec > STOP_SEC:
                    stopped[g] = a0
        for line_id in {g[0] for g in people}:
            mine = [g for g in people if g[0] == line_id]
            down = [g for g in mine if g in stopped]
            line = lines.get(line_id)
            if len(mine) >= 2 and len(down) == len(mine):  # everybody: one alert for the line
                if f"line:{line_id}" not in self.stop_alerted:
                    self.stop_alerted.add(f"line:{line_id}")
                    create_alert("stoppage", "warning", f"{line.name if line else 'Line'}: line stopped, no parts since {hm(min(stopped[g] for g in down))}",
                                 line_id=line_id, dedupe_min=60)
                continue
            self.stop_alerted.discard(f"line:{line_id}")
            for g in down:
                if f"{g[0]}:{g[1]}" in self.stop_alerted:
                    continue
                self.stop_alerted.add(f"{g[0]}:{g[1]}")
                s = sts[jobs[people[g]]["stations"][0]]
                create_alert("stoppage", "warning", f"{g[1]} (step {s.sequence} {s.name}): no cycle since {hm(stopped[g])}",
                             line_id=line_id, station_id=s.id, dedupe_min=60)


feed = DetectorFeed()
