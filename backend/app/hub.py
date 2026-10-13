"""Live state shared between camera worker threads and the async web layer.

- LiveRegistry: latest per-station state (written by camera threads, read by API / websocket).
- EventHub: thread-safe publish of websocket messages to every connected client.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


@dataclass
class _StationState:
    station_id: int
    line_id: int
    state: str = "no_camera"
    cycle_start_ts: float | None = None  # wall-clock (time.time()) when current cycle started
    last_cycle_sec: float | None = None
    count_today: int = 0
    sum_today: float = 0.0
    operator_present: bool = False
    part_present: bool = False
    updated_ts: float = field(default_factory=time.time)
    camera_id: int | None = None


class LiveRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[int, _StationState] = {}
        self._day = date.today()

    # ---- setup
    def reset(self, stations: list[tuple[int, int]], today_stats: dict[int, tuple[int, float, float | None]]) -> None:
        """stations: [(station_id, line_id)], today_stats: station_id -> (count, sum_sec, last_cycle_sec)."""
        with self._lock:
            old = self._states
            self._states = {}
            for sid, lid in stations:
                st = _StationState(station_id=sid, line_id=lid)
                if sid in old:  # keep runtime info of running workers
                    o = old[sid]
                    st.state, st.cycle_start_ts, st.camera_id = o.state, o.cycle_start_ts, o.camera_id
                    st.operator_present, st.part_present, st.updated_ts = o.operator_present, o.part_present, o.updated_ts
                cnt, total, last = today_stats.get(sid, (0, 0.0, None))
                st.count_today, st.sum_today, st.last_cycle_sec = cnt, total, last
                self._states[sid] = st
            self._day = date.today()

    def ensure(self, station_id: int, line_id: int) -> None:
        with self._lock:
            if station_id not in self._states:
                self._states[station_id] = _StationState(station_id=station_id, line_id=line_id)

    def remove(self, station_id: int) -> None:
        with self._lock:
            self._states.pop(station_id, None)

    # ---- updates from camera workers
    def update(self, station_id: int, camera_id: int | None = None, **kw: Any) -> None:
        with self._lock:
            st = self._states.get(station_id)
            if st is None:
                return
            for k, v in kw.items():
                setattr(st, k, v)
            if camera_id is not None:
                st.camera_id = camera_id
            st.updated_ts = time.time()

    def set_offline(self, camera_id: int) -> None:
        with self._lock:
            for st in self._states.values():
                if st.camera_id == camera_id:
                    st.state = "offline"
                    st.operator_present = False
                    st.updated_ts = time.time()

    def release_camera(self, camera_id: int) -> None:
        """Camera removed / disabled: its stations no longer have a camera."""
        with self._lock:
            for st in self._states.values():
                if st.camera_id == camera_id:
                    st.state = "no_camera"
                    st.camera_id = None
                    st.cycle_start_ts = None
                    st.operator_present = st.part_present = False

    def record_cycle(self, station_id: int, cycle_sec: float, at_ts: float) -> None:
        with self._lock:
            self._roll_day()
            st = self._states.get(station_id)
            if st is None:
                return
            st.count_today += 1
            st.sum_today += cycle_sec
            st.last_cycle_sec = cycle_sec
            st.cycle_start_ts = at_ts

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._day:
            for st in self._states.values():
                st.count_today, st.sum_today = 0, 0.0
            self._day = today

    # ---- reads
    def get(self, station_id: int) -> dict | None:
        with self._lock:
            st = self._states.get(station_id)
            return self._to_dict(st, time.time()) if st else None

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self._lock:
            self._roll_day()
            return [self._to_dict(st, now) for st in self._states.values()]

    def as_map(self) -> dict[int, dict]:
        return {d["station_id"]: d for d in self.snapshot()}

    @staticmethod
    def _to_dict(st: _StationState, now: float) -> dict:
        elapsed = None
        if st.cycle_start_ts is not None and st.state not in ("offline", "no_camera"):
            elapsed = round(max(0.0, now - st.cycle_start_ts), 1)
        return {
            "station_id": st.station_id,
            "line_id": st.line_id,
            "state": st.state,
            "cycle_elapsed_sec": elapsed,
            "last_cycle_sec": round(st.last_cycle_sec, 2) if st.last_cycle_sec is not None else None,
            "count_today": st.count_today,
            "avg_today_sec": round(st.sum_today / st.count_today, 2) if st.count_today else None,
            "operator_present": st.operator_present,
            "part_present": st.part_present,
            "updated_at": datetime.fromtimestamp(st.updated_ts),
        }


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json", by_alias=True)
    raise TypeError(f"not serializable: {type(o)}")


class EventHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[str] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=5000)
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, msg_type: str, data: Any) -> None:
        """Thread-safe: may be called from camera worker threads."""
        if self._loop is None or self._queue is None or not self._clients:
            return
        text = json.dumps({"type": msg_type, "data": data}, default=_json_default)
        try:
            self._loop.call_soon_threadsafe(self._enqueue, text)
        except RuntimeError:
            pass  # loop closed during shutdown

    def _enqueue(self, text: str) -> None:
        assert self._queue is not None
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(text)

    async def _pump(self) -> None:
        assert self._queue is not None
        while True:
            text = await self._queue.get()
            dead = []
            for ws in list(self._clients):
                try:
                    await asyncio.wait_for(ws.send_text(text), timeout=2.0)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)


live = LiveRegistry()
hub = EventHub()
