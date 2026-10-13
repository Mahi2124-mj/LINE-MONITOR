"""Saved breakup reports (one folder per report under reports/: index.html + video + frames + data.json + meta.json)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import models
from ..config import settings
from ..database import SessionLocal
from ..services.report_engine import engine

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _folder(name: str):
    d = (settings.reports_dir / name).resolve()
    if d.parent != settings.reports_dir.resolve() or not (d / "index.html").is_file():
        raise HTTPException(404, "report not found")
    return d


@router.get("")
def list_reports():
    out = []
    folders = [d for d in (settings.reports_dir.iterdir() if settings.reports_dir.exists() else [])
               if (d / "index.html").is_file() and d.suffix != ".tmp"]
    for d in folders:
        meta: dict = {}
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        out.append({
            "name": d.name,
            "title": meta.get("title") or d.name,
            "subtitle": meta.get("subtitle"),
            "camera_id": meta.get("camera_id"),
            "station_id": meta.get("station_id"),
            "cameras": meta.get("cameras") or ([meta["camera_id"]] if meta.get("camera_id") else []),
            "auto": bool(meta.get("auto")),
            "date": meta.get("date"),
            "window": meta.get("window"),
            "cycles": meta.get("cycles"),
            "median_cycle": meta.get("median_cycle"),
            "highlights": meta.get("highlights") or [],
            "created_at": datetime.fromtimestamp((d / "index.html").stat().st_mtime).isoformat(timespec="seconds"),
            "size_mb": round(size / 1e6, 1),
        })
    # newest first by the time the report covers (a rebuilt old report keeps its place)
    out.sort(key=lambda r: f"{r['date'] or ''} {(r['window'] or '')[:8]}" if r["date"] else r["created_at"].replace("T", " "), reverse=True)
    return out


@router.get("/status")
def status():
    """Automatic reports: which camera is being done now, queue, last result per camera."""
    return engine.status()


@router.post("/generate/{camera_id}", status_code=202)
async def generate(camera_id: int):  # async: the engine's wake-up event lives on the event loop
    with SessionLocal() as db:
        cam = db.get(models.Camera, camera_id)
        if cam is None or cam.station_id is None:
            raise HTTPException(404, "camera with a station not found")
    engine.request(camera_id)
    return engine.status()


_ASSETS = {"report_player.js": "text/javascript", "report_player.css": "text/css", "report_charts.js": "text/javascript"}


@router.get("/_assets/{file}")
def asset(file: str):
    """Shared player (scrubbable coloured timeline, frame steps, speed) and variation chart of all reports."""
    if file not in _ASSETS:
        raise HTTPException(404)
    return FileResponse(Path(__file__).resolve().parent.parent / "static" / file, media_type=_ASSETS[file],
                        headers={"Cache-Control": "no-cache"})


@router.get("/{name}/")
def report_index(name: str):
    return FileResponse(_folder(name) / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/{name}/{path:path}")
def report_file(name: str, path: str):
    d = _folder(name)
    f = (d / (path or "index.html")).resolve()
    if d not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})  # video: range requests are supported (seeking)
