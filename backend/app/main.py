"""FastAPI application: REST API + websocket + MJPEG streams + (optionally) the built React frontend."""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select

from . import models
from .config import settings
from .database import SessionLocal, init_db
from .hub import hub, live
from .routers import analysis, cameras, dashboard, lines, reports, setup, stations
from .services.analysis import engine as analysis_engine
from .services.report_engine import engine as report_engine
from .services.alerts import engine as alert_engine
from .services.seed import seed_if_empty
from .vision.manager import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# also keep a log file, so a server window that was closed / crashed can be diagnosed later
_fh = RotatingFileHandler(settings.data_dir / "server.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_fh)
logging.getLogger("uvicorn").addHandler(_fh)  # uvicorn loggers don't propagate to the root logger
log = logging.getLogger("line-monitor")


def _log_thread_crash(args: threading.ExceptHookArgs) -> None:
    log.error("thread %s crashed", args.thread.name if args.thread else "?", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


threading.excepthook = _log_thread_crash


async def _broadcast_states() -> None:
    while True:
        await asyncio.sleep(1.0)
        if hub.client_count:
            hub.publish("states", live.snapshot())


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        if settings.demo_mode:
            seed_if_empty(db)
        live.reset([(s.id, s.line_id) for s in db.scalars(select(models.Station))], stations.today_stats(db))
    await hub.start()
    await asyncio.to_thread(manager.start_all)
    await alert_engine.start()
    await analysis_engine.start()
    await report_engine.start()
    bcast = asyncio.create_task(_broadcast_states())
    log.info("Line monitor ready on http://%s:%s (demo=%s)", settings.host, settings.port, settings.demo_mode)
    yield
    bcast.cancel()
    await alert_engine.stop()
    await analysis_engine.stop()
    await report_engine.stop()
    await asyncio.to_thread(manager.stop_all)
    await hub.stop()


app = FastAPI(title="Line Monitoring", version=settings.version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(setup.router)  # before cameras: /api/cameras/probe must not match /api/cameras/{id}
app.include_router(analysis.router)
app.include_router(dashboard.router)
app.include_router(lines.router)
app.include_router(stations.router)
app.include_router(cameras.router)
app.include_router(reports.router)


# ---- serve the built frontend (npm run build) from the same port in production
dist = settings.frontend_dist
if dist.exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        f = (dist / full_path).resolve()
        if full_path and f.is_file() and dist.resolve() in f.parents:
            # hashed build files never change -> cache forever; everything else revalidates
            cache = "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
            return FileResponse(f, headers={"Cache-Control": cache})
        if full_path.startswith("assets/"):
            raise HTTPException(404)  # an old build's file: never answer with index.html
        # index.html must never be cached, otherwise a rebuilt frontend loads deleted chunks (blank page)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})
