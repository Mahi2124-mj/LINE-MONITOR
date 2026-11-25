"""Builds a breakup report of every recorded machine automatically, and on request ("Generate now").

Stations whose work was watched frame by frame have their own breakup report (tools/reports/station_breakup.py for
stations 1-5, tools/reports/final_report.py for the final inspection + bin); any other recorded camera gets the generic
report (app.services.report_gen). Each report is made by a separate low-priority process, one at a time, so the cameras
never slow down. Old automatic reports are removed (newest KEEP_PER_CAMERA kept per job)."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from sqlalchemy import select

from .. import models
from ..config import BACKEND_DIR, settings
from ..database import SessionLocal

log = logging.getLogger(__name__)

REPORT_EVERY_H = 2.0  # a new automatic report per machine every 2 hours (when the line runs)
KEEP_PER_CAMERA = 12
CHECK_SEC = 600
RETRY_AFTER_SEC = 1800  # no usable data last time (line stopped): try again after 30 min
TIMEOUT_SEC = 1500
_RESULT = {0: "ok", 1: "Not enough cycles recorded in the last hour (line stopped / camera offline?)", 2: "Failed (see data/report_gen.log)"}

TOOLS = BACKEND_DIR / "tools" / "reports"
# station breakup jobs: job id -> cameras it covers, command, folder pattern of its automatic reports
STATION_JOBS = {
    "m1": {"cams": (1,), "cmd": [str(TOOLS / "station_breakup.py"), "m1", "--auto"], "pattern": "auto_m1_*[0-9]"},
    "m2": {"cams": (2,), "cmd": [str(TOOLS / "station_breakup.py"), "m2", "--auto"], "pattern": "auto_m2_*[0-9]"},
    "m34": {"cams": (3, 4), "cmd": [str(TOOLS / "station_breakup.py"), "m34", "--auto"], "pattern": "auto_m34_*[0-9]"},
    "m5": {"cams": (5,), "cmd": [str(TOOLS / "station_breakup.py"), "m5", "--auto"], "pattern": "auto_m5_*[0-9]"},
    "final:6": {"cams": (6, 7), "cmd": [str(TOOLS / "final_report.py"), "--auto"], "pattern": "auto_final_*[0-9]"},
    # YRA line steps 1-3 (one operator runs all three machines; camera .30 recorded as camera 8)
    "yur": {"cams": (8,), "stations": (8,), "cmd": [str(TOOLS / "station_breakup.py"), "yur", "--auto"], "pattern": "auto_yur_*[0-9]"},
    "yhs": {"cams": (8,), "stations": (14,), "cmd": [str(TOOLS / "station_breakup.py"), "yhs", "--auto"], "pattern": "auto_yhs_*[0-9]"},
    "yxl": {"cams": (8,), "stations": (15,), "cmd": [str(TOOLS / "station_breakup.py"), "yxl", "--auto"], "pattern": "auto_yxl_*[0-9]"},
    # YRA line steps 4-5 (one operator runs both Guide S/A Insert machines; camera .32 recorded as camera 9)
    "yg1": {"cams": (9,), "stations": (9,), "cmd": [str(TOOLS / "station_breakup.py"), "yg1", "--auto"], "pattern": "auto_yg1_*[0-9]"},
    "yg2": {"cams": (9,), "stations": (10,), "cmd": [str(TOOLS / "station_breakup.py"), "yg2", "--auto"], "pattern": "auto_yg2_*[0-9]"},
    # YRA line steps 6-8 (camera .34 recorded as camera 18): operator A runs the greasing and Rr machines and loads the Fr
    # machine; operator B works the rail out of the Fr nest
    "ylr": {"cams": (18,), "stations": (18,), "cmd": [str(TOOLS / "station_breakup.py"), "ylr", "--auto"], "pattern": "auto_ylr_*[0-9]"},
    "ysr": {"cams": (18,), "stations": (17,), "cmd": [str(TOOLS / "station_breakup.py"), "ysr", "--auto"], "pattern": "auto_ysr_*[0-9]"},
    "ysf": {"cams": (18,), "stations": (19,), "cmd": [str(TOOLS / "station_breakup.py"), "ysf", "--auto"], "pattern": "auto_ysf_*[0-9]"},
    # YRA line: Mechanical Movement (left person on the final-area camera)
    "yml": {"cams": (13,), "stations": (13,), "cmd": [str(TOOLS / "station_breakup.py"), "yml", "--auto"], "pattern": "auto_yml_*[0-9]"},
    # YRA line: Mechanical Movement #2 (middle person on the final-area camera)
    "ymm": {"cams": (13,), "stations": (20,), "cmd": [str(TOOLS / "station_breakup.py"), "ymm", "--auto"], "pattern": "auto_ymm_*[0-9]"},
    # YRA line: Final Inspection (right person on the same camera). Validated on 4 layouts (teal tray, blue bin night and
    # after midnight, grey boxes); a built-in check against Mechanical Movement leaves out 10-minute blocks that do not agree.
    "yfi": {"cams": (13,), "stations": (11, 21), "cmd": [str(TOOLS / "station_breakup.py"), "yfi", "--auto"], "pattern": "auto_yfi_*[0-9]"},
    # YWD SS line (one camera, .213 recorded as camera 22): the right person tapes the rails (station 23), the left person
    # works them at machine YJC-SS-09 (station 22)
    "yjc": {"cams": (22,), "stations": (22,), "cmd": [str(TOOLS / "station_breakup.py"), "yjc", "--auto"], "pattern": "auto_yjc_*[0-9]"},
    "ytp": {"cams": (22,), "stations": (23,), "cmd": [str(TOOLS / "station_breakup.py"), "ytp", "--auto"], "pattern": "auto_ytp_*[0-9]"},
}


def _jobs_available() -> dict:
    from pathlib import Path

    return {k: v for k, v in STATION_JOBS.items() if Path(v["cmd"][0]).exists()}


def _pattern(job: int | str) -> str:
    return STATION_JOBS[job]["pattern"] if job in STATION_JOBS else f"auto_cam{job}_*[0-9]"


def auto_reports(job: int | str) -> list:
    """Finished automatic reports of a job, oldest first."""
    return sorted((p for p in settings.reports_dir.glob(_pattern(job)) if (p / "index.html").is_file()), key=lambda p: p.name)


def jobs_for_camera(camera_id: int) -> list[int | str]:
    """Report jobs for a camera's "Generate now". Two stations can share one camera (YRA Mechanical Movement / Final
    Inspection both use camera 13); a job with "stations" belongs to those stations' cameras only."""
    with SessionLocal() as db:
        cam = db.get(models.Camera, camera_id)
        sid = cam.station_id if cam else None
    avail = _jobs_available()
    jobs = [k for k, v in avail.items() if sid is not None and sid in v.get("stations", ())]
    jobs = jobs or [k for k, v in avail.items() if camera_id in v["cams"] and not v.get("stations")]
    return jobs or [camera_id]  # a camera without its own station breakup gets the generic report


class ReportEngine:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.queue: list[int | str] = []
        self.running: int | str | None = None
        self.last: dict[int | str, dict] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def request(self, camera_id: int) -> None:
        for job in jobs_for_camera(camera_id):
            if job != self.running and job not in self.queue:
                self.queue.append(job)
        self._wake.set()

    def status(self) -> dict:
        cams = {str(k): list(v["cams"]) for k, v in _jobs_available().items()}
        last: dict = {}
        for job, v in self.last.items():  # also per camera, so the page can show the result under each machine
            last[str(job)] = v
            for cam in cams.get(str(job), []):
                last.setdefault(str(cam), v)
        stations = {str(k): list(v["stations"]) for k, v in _jobs_available().items() if v.get("stations")}
        return {"running": self.running, "queue": list(self.queue), "last": last, "job_cams": cams, "job_stations": stations,
                "every_hours": REPORT_EVERY_H, "keep_per_camera": KEEP_PER_CAMERA}

    # ---------------------------------------------------------------- loop
    async def _loop(self) -> None:
        await asyncio.sleep(90)
        while True:
            try:
                for job in await asyncio.to_thread(self._due):
                    if job not in self.queue and job != self.running:
                        self.queue.append(job)
                while self.queue:
                    job = self.queue.pop(0)
                    await self._run(job)
                    await asyncio.to_thread(self._prune, job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("report engine error")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), CHECK_SEC)
            except asyncio.TimeoutError:
                pass

    def _due(self) -> list[int | str]:
        with SessionLocal() as db:
            active = {line.id for line in db.scalars(select(models.Line)) if line.is_active}  # a disabled line gets no reports
            cams = [c for c in db.scalars(select(models.Camera))
                    if c.enabled and c.station_id and c.line_id in active and (c.config or {}).get("record")]
        ids = {c.id for c in cams}
        jobs: list[int | str] = []
        for k, v in _jobs_available().items():
            if all(c in ids for c in v["cams"]):
                jobs.append(k)
        covered = {c for k in jobs for c in STATION_JOBS[k]["cams"]}
        jobs += [c for c in sorted(ids) if c not in covered]
        due, now = [], time.time()
        for job in jobs:
            done = auto_reports(job)
            if done and now - (done[-1] / "index.html").stat().st_mtime < REPORT_EVERY_H * 3600:
                continue
            last = self.last.get(job)
            if last and not last["ok"] and now - last["ts"] < RETRY_AFTER_SEC:
                continue
            due.append(job)
        return due

    async def _run(self, job: int | str) -> None:
        self.running = job
        started = time.time()
        env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONIOENCODING="utf-8")
        flags = 0x00004000 | 0x08000000 if sys.platform == "win32" else 0  # below-normal priority, no window
        cmd = [sys.executable, *STATION_JOBS[job]["cmd"]] if job in STATION_JOBS else [sys.executable, "-m", "app.services.report_gen", str(job)]
        try:
            proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(BACKEND_DIR), env=env, creationflags=flags,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT_SEC)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = 2
        finally:
            self.running = None
        self.last[job] = {"ok": rc == 0, "message": _RESULT.get(rc, _RESULT[2]), "ts": time.time(),
                          "at": datetime.now().isoformat(timespec="seconds"), "seconds": round(time.time() - started)}
        log.info("report %s: %s (%.0fs)", job, self.last[job]["message"], time.time() - started)

    def _prune(self, job: int | str) -> None:
        for old in auto_reports(job)[:-KEEP_PER_CAMERA]:
            shutil.rmtree(old, ignore_errors=True)
        for tmp in settings.reports_dir.glob(_pattern(job).replace("[0-9]", ".tmp")):  # left over by an interrupted run
            if time.time() - tmp.stat().st_mtime > 3600:
                shutil.rmtree(tmp, ignore_errors=True)


engine = ReportEngine()
