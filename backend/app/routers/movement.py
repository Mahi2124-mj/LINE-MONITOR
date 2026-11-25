"""Shift movement reports (one folder per shift run under data/movement_reports: report.json, meta.json, walking maps,
clips)."""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.movement_reports import REPORTS, engine, report_dir

router = APIRouter(prefix="/api/movement-reports", tags=["movement"])
_FILE = re.compile(r"^(clip_\d+\.webm|map_cam\d+\.jpg)$")


def _load(d) -> tuple[dict, dict]:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return rep, meta


@router.get("")
def list_reports():
    out = []
    for d in (REPORTS.iterdir() if REPORTS.exists() else []):
        if not d.is_dir() or "." in d.name or not (d / "report.json").is_file():
            continue
        try:
            rep, meta = _load(d)
        except (OSError, ValueError):
            continue
        out.append({"id": d.name, "title": rep.get("title"), "shift": meta.get("shift"), "day": meta.get("day"),
                    "partial": bool(meta.get("partial")), "window": rep.get("window"), "generated_at": rep.get("generated_at"),
                    "operators": [{"name": o["name"], "color": o["color"], "measured": o.get("measured", 0),
                                   "extra_avg": o.get("extra_avg"), "extra_share": o.get("extra_share")} for o in rep.get("operators", [])]})
    out.sort(key=lambda r: (r["window"] or [0])[0], reverse=True)
    return out


@router.get("/status")
def status():
    return engine.status()


@router.post("/generate", status_code=202)
async def generate(shift: Literal["A", "B"] = "A", which: Literal["current", "last"] = "last"):
    """make the report of the running shift so far (current) or of its last finished run (last) now"""
    engine.request(shift, which == "current")
    return engine.status()


@router.get("/{rid}")
def get_report(rid: str):
    d = report_dir(rid)
    if d is None:
        raise HTTPException(404, "report not found")
    rep, meta = _load(d)
    return {"id": rid, **meta, **rep}


@router.get("/{rid}/{name}")
def report_file(rid: str, name: str):
    d = report_dir(rid)
    if d is None or not _FILE.match(name) or not (d / name).is_file():
        raise HTTPException(404)
    return FileResponse(d / name, headers={"Cache-Control": "no-cache"})  # video: range requests are supported (seeking)
