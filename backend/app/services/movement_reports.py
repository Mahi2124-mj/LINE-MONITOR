"""Shift movement reports (tools/reports/movement_report.py): how much each YRA operator moves compared with his own best
cycles, his walking map, unusual actions with video. One report per shift run, made AFTER_END after the shift ends (the
step detectors store the last cycles a few minutes late) while the recording of the whole shift is still kept (12 h);
on request also for the running shift so far. One report at a time, in a low-priority process."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from .. import models
from ..config import BACKEND_DIR, settings
from ..database import SessionLocal
from .analytics import _shift_run

log = logging.getLogger(__name__)

TOOL = BACKEND_DIR / "tools" / "reports" / "movement_report.py"
REPORTS = settings.data_dir / "movement_reports"
LINE_STATION = 14          # the tool's operators are the YRA line's (station 14 = YRA step 2)
SHIFTS = ("A", "B")
AFTER_END = timedelta(minutes=25)
MAX_AGE = timedelta(hours=10)   # the recording is kept 12 h: an older shift is no longer complete
MIN_CYCLES = 50            # fewer detector cycles in a shift: the line did not run (holiday), no report
KEEP_DAYS = 21
TIMEOUT_SEC = 3600
CHECK_SEC = 600


def report_dir(rid: str) -> Path | None:
    d = (REPORTS / rid).resolve()
    return d if d.parent == REPORTS.resolve() and (d / "report.json").is_file() else None


class MovementReports:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self.queue: list[tuple[str, bool]] = []   # (shift, current) asked for on the page
        self.running: str | None = None
        self.last: dict = {}
        self.skipped: set[str] = set()           # shift runs without production (no report)

    async def start(self) -> None:
        if not TOOL.exists():
            return
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def status(self) -> dict:
        return {"running": self.running, "queue": [f"Shift {s}{' (so far)' if c else ''}" for s, c in self.queue], "last": self.last,
                "after_end_min": int(AFTER_END.total_seconds() // 60), "keep_days": KEEP_DAYS}

    def request(self, shift: str, current: bool) -> None:
        if (shift, current) not in self.queue:
            self.queue.append((shift, current))
        if self._wake:
            self._wake.set()

    # ---------------------------------------------------------------- which shift runs
    @staticmethod
    def _line() -> models.Line | None:
        with SessionLocal() as db:
            st = db.get(models.Station, LINE_STATION)
            line = db.get(models.Line, st.line_id) if st else None
            if line is not None:
                db.expunge(line)
        return line if line is not None and line.is_active and line.slot_plan else None

    @staticmethod
    def _run_of(line: models.Line, shift: str, now: datetime, current: bool) -> tuple[datetime, datetime, bool] | None:
        """(start, end, still running) of the running / newest run of a shift (current), else of its last finished run"""
        rows = _shift_run(line, shift, now)
        if rows and not current and rows[-1][1] > now:
            rows = _shift_run(line, shift, rows[0][0] - timedelta(minutes=1))
        if not rows:
            return None
        start, end = rows[0][0], rows[-1][1]
        return (start, min(end, now), end > now)

    @staticmethod
    def _cycles(line_id: int, start: datetime, end: datetime) -> int:
        with SessionLocal() as db:
            return db.scalar(select(func.count(models.Cycle.id)).where(
                models.Cycle.line_id == line_id, models.Cycle.source == "detector",
                models.Cycle.started_at >= start, models.Cycle.started_at < end)) or 0

    def _due(self) -> list[tuple[str, datetime, datetime, bool]]:
        line = self._line()
        if line is None:
            return []
        now, out = datetime.now(), []
        for shift in SHIFTS:
            run = self._run_of(line, shift, now, current=False)
            if run is None:
                continue
            start, end, _ = run
            rid = f"{start:%Y%m%d}_{shift}"
            if not (end + AFTER_END <= now <= end + MAX_AGE) or rid in self.skipped:
                continue
            d = report_dir(rid)
            if d is not None and not _meta(d).get("partial"):
                continue
            if self._cycles(line.id, start, end) < MIN_CYCLES:
                self.skipped.add(rid)
                continue
            out.append((shift, start, end, False))
        return out

    def _asked(self, shift: str, current: bool) -> tuple[str, datetime, datetime, bool] | None:
        line = self._line()
        if line is None:
            self.last = {"ok": False, "message": "The line has no time slots.", "at": datetime.now().isoformat(timespec="seconds")}
            return None
        now = datetime.now()
        run = self._run_of(line, shift, now, current)
        if run is None or now - run[1] > MAX_AGE:
            self.last = {"ok": False, "message": f"Shift {shift}: no run with its recording still kept (12 h).",
                         "at": now.isoformat(timespec="seconds")}
            return None
        return (shift, *run)

    # ---------------------------------------------------------------- loop
    async def _loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            try:
                for job in await asyncio.to_thread(self._due):
                    await self._run(*job)
                while self.queue:
                    job = await asyncio.to_thread(self._asked, *self.queue[0])
                    if job:
                        await self._run(*job)
                    self.queue.pop(0)
                await asyncio.to_thread(_prune)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("movement report error")
            try:
                await asyncio.wait_for(self._wake.wait(), CHECK_SEC)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _run(self, shift: str, start: datetime, end: datetime, partial: bool) -> None:
        rid = f"{start:%Y%m%d}_{shift}"
        final, tmp = REPORTS / rid, REPORTS / f"{rid}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        title = f"Shift {shift} · {start:%d %b} · {start:%H:%M}–{end:%H:%M}{' (so far)' if partial else ''}"
        env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONIOENCODING="utf-8")
        flags = 0x00004000 | 0x08000000 if sys.platform == "win32" else 0  # below-normal priority, no window
        cmd = [sys.executable, str(TOOL), f"{start.timestamp():.0f}", f"{end.timestamp():.0f}", str(tmp), "--title", title]
        self.running, began = title, time.time()
        try:
            proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(BACKEND_DIR), env=env, creationflags=flags,
                                           capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SEC)
            ok = (tmp / "report.json").is_file()
            msg = "" if ok else (proc.stderr or "").strip().splitlines()[-1:] or ["no report written"]
        except subprocess.TimeoutExpired:
            ok, msg = False, ["timed out"]
        finally:
            self.running = None
        if ok:
            (tmp / "meta.json").write_text(json.dumps({"shift": shift, "day": f"{start:%Y-%m-%d}", "start": start.isoformat(),
                                                       "end": end.isoformat(), "partial": partial}), encoding="utf-8")
            await asyncio.to_thread(_replace, tmp, final)
        self.last = {"ok": ok, "report": rid if ok else None, "title": title, "seconds": round(time.time() - began),
                     "message": "" if ok else str(msg[0])[:300], "at": datetime.now().isoformat(timespec="seconds")}
        log.info("movement report %s: %s (%ds)", title, "ok" if ok else self.last["message"], self.last["seconds"])


def _meta(d: Path) -> dict:
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _replace(tmp: Path, final: Path) -> None:
    """the new report in place of the old one (an old one whose clip is being played is moved aside, removed later)"""
    if final.exists():
        shutil.rmtree(final, ignore_errors=True)
        if final.exists():
            final.rename(final.with_name(f"{final.name}.old{int(time.time())}"))
    tmp.rename(final)


def _prune() -> None:
    if not REPORTS.exists():
        return
    floor = datetime.now() - timedelta(days=KEEP_DAYS)
    for d in REPORTS.iterdir():
        if not d.is_dir():
            continue
        if ".old" in d.name or d.name.endswith(".tmp"):
            if time.time() - d.stat().st_mtime > 86400:
                shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            day = datetime.strptime(d.name[:8], "%Y%m%d")
        except ValueError:
            continue
        if day < floor:
            shutil.rmtree(d, ignore_errors=True)


engine = MovementReports()
