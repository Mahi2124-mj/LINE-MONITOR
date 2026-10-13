"""Demo data: 3 lines with simulated cameras + a few days of statistically generated history."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..vision import synthetic as syn

log = logging.getLogger(__name__)

# name, parts, operation, target, expected picks, sim profile (speed, far reach, walk, extra pick)
DEMO = [
    {
        "name": "Line A – Smart Meter Assembly", "code": "LA", "takt": 42.0,
        "description": "Single-phase smart energy meter, 6-step manual assembly line.",
        "stations": [
            ("Base Prep", ["Base housing", "Gasket"], "Load base housing on fixture and seat the gasket", 34, 2, (0.95, 0.05, 0.02, 0.05)),
            ("PCB Mount", ["Main PCB", "Screw M3 ×4"], "Place main PCB on bosses and tighten 4 screws", 38, 2, (1.06, 0.35, 0.03, 0.15)),
            ("Display Fit", ["LCD display", "FPC cable"], "Fit LCD module and connect the FPC cable", 36, 2, (0.95, 0.05, 0.02, 0.05)),
            ("Battery & Wiring", ["Battery pack", "Wire harness"], "Insert backup battery, route and clip harness", 34, 2, (1.0, 0.12, 0.3, 0.1)),
            ("Cover Close", ["Top cover", "Screw M3 ×2"], "Snap top cover and fit 2 screws", 30, 2, (0.92, 0.02, 0.01, 0.05)),
            ("Test & Label", ["Serial label"], "Functional test, print and paste serial label", 35, 1, (0.96, 0.1, 0.05, 0.05)),
        ],
    },
    {
        "name": "Line B – Ceiling Fan Motor", "code": "LB", "takt": 50.0,
        "description": "Fan motor sub-assembly line, 5 steps.",
        "stations": [
            ("Stator Insert", ["Stator", "Motor housing"], "Press stator into the housing", 42, 2, (1.0, 0.05, 0.03, 0.05)),
            ("Rotor & Shaft", ["Rotor", "Shaft", "Bearing ×2"], "Assemble rotor on shaft, press both bearings", 44, 3, (1.0, 0.2, 0.03, 0.08)),
            ("Blade Mount", ["Blade set", "Hub nut"], "Mount blade set and torque hub nut", 42, 2, (1.06, 0.08, 0.04, 0.4)),
            ("Capacitor Wiring", ["Capacitor", "Terminal block"], "Fit capacitor and wire terminal block", 38, 2, (1.0, 0.05, 0.2, 0.05)),
            ("Inspection & Pack", ["Carton", "User manual"], "Final inspection, pack with manual", 40, 2, (0.95, 0.05, 0.05, 0.05)),
        ],
    },
    {
        "name": "Line C – Modular Switch Board", "code": "LC", "takt": 30.0,
        "description": "Switch board assembly, 4 steps, high volume.",
        "stations": [
            ("Frame Load", ["Plate frame"], "Load plate frame on fixture", 22, 1, (1.0, 0.05, 0.02, 0.05)),
            ("Switch Fitting", ["Switch ×4"], "Snap 4 switches into the frame", 27, 4, (1.08, 0.25, 0.02, 0.1)),
            ("Socket & Indicator", ["Socket", "LED indicator"], "Fit socket and LED indicator", 24, 2, (1.0, 0.05, 0.02, 0.05)),
            ("Back Cover & Pack", ["Back cover", "Screw ×2", "Poly bag"], "Fit back cover, screw and bag", 23, 3, (1.0, 0.05, 0.12, 0.05)),
        ],
    },
]

BREAKS = [((10, 30), (10, 40)), ((13, 0), (13, 30)), ((16, 0), (16, 10))]


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(func.count(models.Line.id))):
        return False
    log.info("Seeding demo data ...")
    rng = random.Random(42)
    for li, spec in enumerate(DEMO):
        line = models.Line(name=spec["name"], code=spec["code"], description=spec["description"], takt_time_sec=spec["takt"],
                           shift_start="08:00", shift_end="20:00")
        db.add(line)
        db.flush()
        stations = []
        for si, (name, parts, op, target, picks, prof) in enumerate(spec["stations"], start=1):
            st = models.Station(line_id=line.id, sequence=si, name=name, code=f"{spec['code']}-S{si}", operation=op, parts_added=parts,
                                target_cycle_sec=float(target), expected_picks=picks, operator_name=f"Operator {spec['code']}{si}")
            db.add(st)
            db.flush()
            stations.append((st, prof))
            speed, far, walk, extra = prof
            cam = models.Camera(
                line_id=line.id, station_id=st.id, name=f"CAM-{spec['code']}{si} · {name}", source_type="simulated", source="sim",
                zones=syn.demo_zones(),
                config={"cycle_method": "part_presence", "tracker": "simulated", "process_fps": 6, "min_cycle_sec": 5,
                        "max_cycle_sec": 600, "presence_threshold": 0.15, "presence_debounce_sec": 0.8, "idle_timeout_sec": 10,
                        "meters_per_frame_width": 2.5, "analyzers": ["cycle_time", "movement", "heatmap"],
                        "sim": {"speed_factor": speed, "far_reach_prob": far, "walk_prob": walk, "extra_pick_prob": extra}},
            )
            db.add(cam)
            db.flush()
            stations[-1] = (st, prof, cam)
        _history(db, line, stations, rng)
    _demo_alerts(db)
    db.commit()
    log.info("Demo data ready")
    return True


def _in_break(t: datetime) -> datetime | None:
    for (bh, bm), (eh, em) in BREAKS:
        a, b = t.replace(hour=bh, minute=bm, second=0, microsecond=0), t.replace(hour=eh, minute=em, second=0, microsecond=0)
        if a <= t < b:
            return b
    return None


def _history(db: Session, line: models.Line, stations: list, rng: random.Random) -> None:
    now = datetime.now()
    rows: list[dict] = []
    heat_days: dict[str, list[tuple]] = {}
    for back in range(settings.demo_history_days, -1, -1):
        day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        t = day.replace(hour=8)
        end = min(day.replace(hour=20), now - timedelta(minutes=2))
        if end <= t:
            continue
        after_gap = True
        units = 0
        while t < end:
            b = _in_break(t)
            if b is not None:
                t, after_gap = b, True
                continue
            if rng.random() < 0.003:  # stoppage: material shortage / breakdown
                t += timedelta(seconds=rng.uniform(120, 480))
                after_gap = True
                continue
            fatigue = 1 + 0.03 * ((t.hour + t.minute / 60) - 8) / 12
            per = []
            for st, (speed, far, walk, extra), cam in stations:
                exp_p = max(1, st.expected_picks)
                picks = exp_p + (1 if rng.random() < extra else 0)
                n_far = sum(1 for _ in range(picks) if rng.random() < far)
                walked = rng.random() < walk
                standard = st.target_cycle_sec * speed * fatigue * rng.lognormvariate(0, 0.07)
                if rng.random() < 0.03:
                    standard += min(rng.expovariate(1 / 5), 12.0)
                work = standard + (picks - exp_p) * 3.2 + rng.uniform(-0.5, 0.5)
                motion = n_far * rng.uniform(1.8, 2.6) + (rng.uniform(6.2, 8.4) if walked else 0.0) + rng.uniform(0, 0.4)
                per.append((st, cam, picks, n_far, walked, work, motion))
            pace = max(w + m for *_, w, m in per) + 2.6 + rng.uniform(0, 0.8)
            for i, (st, cam, picks, n_far, walked, work, motion) in enumerate(per):
                content = work + motion
                cyc = (content + 2.6 + rng.uniform(0, 0.6)) if after_gap else max(content + 0.4, pace + rng.uniform(-0.4, 0.4))
                ended = t + timedelta(seconds=pace + i * 0.7)
                rows.append({
                    "station_id": st.id, "line_id": line.id, "camera_id": cam.id,
                    "started_at": ended - timedelta(seconds=cyc), "ended_at": ended,
                    "cycle_sec": round(cyc, 2), "work_sec": round(work, 2), "motion_waste_sec": round(motion, 2),
                    "wait_sec": round(max(0.0, cyc - content), 2),
                    "hand_travel_m": round(min(picks, picks - n_far) * 1.45 + n_far * 3.0 + work * 0.18 + rng.uniform(-0.3, 0.3), 2),
                    "reach_count": n_far + (1 if rng.random() < 0.04 else 0),
                    "walk_m": round(rng.uniform(3.0, 4.0) if walked else rng.uniform(0, 0.15), 2),
                    "pick_count": picks, "source": "seed", "over_target": content > st.target_cycle_sec, "track": None,
                })
            t += timedelta(seconds=pace)
            after_gap = False
            units += 1
        heat_days[day.date().isoformat()] = [(st, prof, cam, units) for st, prof, cam in stations]
    if rows:
        db.execute(insert(models.Cycle), rows)
    for d, items in heat_days.items():
        for st, (speed, far, walk, extra), cam, units in items:
            db.add(models.HeatmapDay(camera_id=cam.id, day=d, cols=settings.heatmap_cols, rows=settings.heatmap_rows,
                                     grid=_heat_grid(units, st.target_cycle_sec * speed, far, walk).tolist()))


def _heat_grid(units: int, cycle: float, far: float, walk: float) -> np.ndarray:
    cols, rows = settings.heatmap_cols, settings.heatmap_rows
    xs = (np.arange(cols) + 0.5) / cols
    ys = (np.arange(rows) + 0.5) / rows
    X, Y = np.meshgrid(xs, ys)

    def bump(cx: float, cy: float, sx: float, sy: float, w: float) -> np.ndarray:
        return w * np.exp(-(((X - cx) / sx) ** 2 + ((Y - cy) / sy) ** 2) / 2)

    total = units * cycle
    g = bump(syn.FIX_L[0], syn.FIX_L[1], 0.03, 0.04, 0.55) + bump(syn.FIX_R[0], syn.FIX_R[1], 0.03, 0.04, 0.55)
    g += bump(syn.REST_L[0], syn.REST_L[1], 0.03, 0.03, 0.12) + bump(syn.REST_R[0], syn.REST_R[1], 0.03, 0.03, 0.12)
    for b in syn.BINS[:2]:
        g += bump(b["center"][0], b["center"][1], 0.035, 0.04, 0.08)
    g += bump(syn.BINS[2]["center"][0], syn.BINS[2]["center"][1], 0.03, 0.04, 0.5 * far)
    g += bump(1.0, 0.88, 0.05, 0.05, 0.3 * walk)
    g = g / g.sum() * total * 2  # two hands
    return np.round(g, 2).reshape(-1)


def _demo_alerts(db: Session) -> None:
    lines = db.scalars(select(models.Line)).all()
    now = datetime.now()
    for line in lines:
        db.add(models.Alert(line_id=line.id, type="unbalanced", severity="info",
                            message=f"{line.name}: line balance below 85% in the previous shift — review the Yamazumi chart",
                            created_at=now - timedelta(days=1, hours=3), acknowledged=True, acknowledged_at=now - timedelta(days=1)))
