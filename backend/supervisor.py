"""Keeps the Line Monitor server running: restarts it automatically if it stops unexpectedly
(e.g. Windows ran out of memory). "Stop Line Monitor.bat" writes data/stop.flag so a deliberate stop is not undone.

Started (windowless) by "Start Line Monitor.bat":  .venv\\Scripts\\pythonw.exe supervisor.py
"""
from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)
STOP_FLAG = DATA / "stop.flag"
RESTART_DELAY = 5
CREATE_NO_WINDOW = 0x08000000

logging.basicConfig(
    filename=DATA / "supervisor.log", level=logging.INFO, format="%(asctime)s %(levelname)s supervisor: %(message)s", encoding="utf-8"
)
log = logging.getLogger()


def single_instance() -> bool:
    """Only one supervisor per PC (a named Windows mutex, released automatically when the process ends)."""
    if sys.platform != "win32":
        return True
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LineMonitorSupervisor")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    if not single_instance():
        log.info("another supervisor is already running - exiting")
        return
    STOP_FLAG.unlink(missing_ok=True)
    restarts: list[float] = []
    while True:
        log.info("starting server")
        proc = subprocess.Popen([sys.executable, "run.py"], cwd=HERE, creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        code = proc.wait()
        if STOP_FLAG.exists():
            log.info("server stopped by user (exit code %s)", code)
            STOP_FLAG.unlink(missing_ok=True)
            return
        now = time.time()
        restarts = [t for t in restarts if now - t < 600] + [now]
        delay = RESTART_DELAY if len(restarts) <= 5 else 60  # crash loop: back off
        log.warning("server exited unexpectedly (code %s) - restarting in %ss", code, delay)
        time.sleep(delay)
        if STOP_FLAG.exists():
            STOP_FLAG.unlink(missing_ok=True)
            return


if __name__ == "__main__":
    main()
