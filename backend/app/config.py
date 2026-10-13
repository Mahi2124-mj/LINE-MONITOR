"""Runtime settings. Override any value with an environment variable (prefix LM_)."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"LM_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


class Settings:
    version = "1.0.0"

    # One port for everything (UI + API + live video), reachable from the LAN / Tailscale on every network card.
    # Port 6002 is used by another project on this PC, so 6010 is used here.
    # Set LM_HOST=127.0.0.1 to allow only this PC again.
    host: str = _env("HOST", "0.0.0.0")
    port: int = int(_env("PORT", "6010"))

    data_dir: Path = Path(_env("DATA_DIR", str(BACKEND_DIR / "data")))
    db_path: Path = Path(_env("DB_PATH", str(data_dir / "line_monitor.db")))
    references_dir: Path = data_dir / "references"
    # recordings for cycle / element analysis (MJPEG segments + pose json-lines) and cut cycle clips
    recordings_dir: Path = Path(_env("RECORDINGS_DIR", str(data_dir / "recordings")))
    clips_dir: Path = data_dir / "clips"
    # saved breakup reports (one folder each: index.html + video + data), shown on the Reports page
    reports_dir: Path = Path(_env("REPORTS_DIR", str(PROJECT_DIR / "reports")))
    record_retention_hours: float = float(_env("RECORD_RETENTION_HOURS", "12"))

    # Demo mode (off by default): seeds 3 example lines with simulated cameras when the DB is empty.
    demo_mode: bool = _env_bool("DEMO", False)
    demo_history_days: int = int(_env("DEMO_HISTORY_DAYS", "3"))

    # Vision
    pose_model: Path = Path(_env("POSE_MODEL", str(BACKEND_DIR / "models" / "yolo11n-pose.pt")))
    pose_device: str = _env("POSE_DEVICE", "cpu")  # e.g. "cuda:0" when a GPU + CUDA torch is installed
    pose_imgsz: int = int(_env("POSE_IMGSZ", "640"))
    pose_conf: float = float(_env("POSE_CONF", "0.35"))
    process_width: int = int(_env("PROCESS_WIDTH", "640"))
    stream_fps: float = float(_env("STREAM_FPS", "10"))
    jpeg_quality: int = int(_env("JPEG_QUALITY", "70"))

    heatmap_cols: int = 48
    heatmap_rows: int = 27

    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.references_dir.mkdir(parents=True, exist_ok=True)
settings.recordings_dir.mkdir(parents=True, exist_ok=True)
settings.clips_dir.mkdir(parents=True, exist_ok=True)
settings.reports_dir.mkdir(parents=True, exist_ok=True)
