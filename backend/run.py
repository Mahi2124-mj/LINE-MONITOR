"""Start the backend:  .venv\\Scripts\\python run.py   (the Start button runs it windowless with pythonw)"""
import os
import sys

# CPU threads for the pose model. Must be set before torch is imported: by default every inference
# spins a busy-waiting thread per core, which burned ~8 cores for 7 cameras instead of ~2.5.
_threads = os.environ.get("LM_TORCH_THREADS", "4")
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, _threads)
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
os.environ.setdefault("KMP_BLOCKTIME", "0")
# no usage analytics / downloads from the YOLO library: factory data stays on this PC
os.environ.setdefault("YOLO_OFFLINE", "1")

from app.config import settings  # noqa: E402

if sys.stdout is None or sys.stderr is None:
    # started without a console (pythonw): keep library prints / tracebacks in a file instead of crashing
    _console = open(settings.data_dir / "console.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _console
    sys.stderr = sys.stderr or _console

import uvicorn  # noqa: E402

if __name__ == "__main__":
    # single worker on purpose: camera threads live inside this process
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False, workers=1, log_level="info")
