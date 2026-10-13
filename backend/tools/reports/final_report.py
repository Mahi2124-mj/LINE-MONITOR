"""Final station report: inspection timing (camera 6) + bin / tray / separator timing (camera 7), from the recordings.

What the inspection operator does (watched frame by frame on 2026-10-10, 00:22-00:35, 9 frames/s):
  - at the inspection machine (camera 6, back to the camera): load the rail, machine check, take it out; then turns
    to the bin in front of him and bends over it to put the rail into the tray - one rail per trip, ~2 s.
  - after the 5th rail of a tray he also lays the upper separator (white comb): that bin visit takes ~7-9 s.
  - after ~10 rails the tray is full: mesh folded over it, an empty tray put on top, its separators set (~13-15 s).
  - now and then a full stack goes onto the rollers and a new bin is set up (plastic sheet + separators).
Camera 7 looks at the bin from above: every visit of his hands shows as motion in the bin zone, and a new empty tray
as a sudden drop of the dark share (black rails covered by an empty blue tray).

Measurement:
  bin visit  = camera-7 motion in the bin zone while camera 6 shows the operator at the bin (bent / left of it);
                 visits a few seconds apart while he stays at the bin are one visit.
  rail         = every bin visit (he brings one rail per machine trip); a visit up to 4.5 s = only the rail.
  separator    = a longer visit without a new tray: rail + upper separator (separator = visit - median rail time);
                 after a new tray: from the moment the empty tray is in place until his hands leave the bin.
  tray change  = the visit with the new-tray drop: from its start until the empty tray is in place
                 (incl. the last rail, its median time is taken out).
  between two bin visits (at the machine), split at the moments the rail goes onto the machine bed and comes off it:
    in-hand check before the machine (bed empty, new rail in his hands) -> in the machine (rail on the bed: load +
    machine check) -> in-hand check after the machine (rail lifted until it goes into the tray);
    load = rail seen on the bed or operator upright in front of it, unload = last upright moment at the machine before
    turning to the bin (checked on 8 cycles: load +-1.7 s, unload +-0.6 s). "Other work" (bent far right) is cut out;
    gaps over 40 s = stop.

usage: python final_report.py <stats from> <stats to> <video from> <video to> [YYYY-MM-DD]
       python final_report.py --auto          (last hour of statistics, latest ~5.5 min as video; used by the report engine)
"""
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.report_gen import (CHARTS_BODY, PLAYER_BODY, PLAYER_HEAD, VARIATION_HTML, load_frames, publish,  # noqa: E402
                                     read_frame, timeline, variation_data)

INSPECTION_CAM, BIN_CAM, STATION_ID = 6, 7, 6
MOTION = 0.05     # share of moving pixels in the bin zone = hands working there
NEAR_X = 0.37     # operator box centre left of this = at the bin
JOIN = 3.0        # visits closer than this while he stays at the bin = one visit
LONG = 4.5        # longer visit without a new tray = rail + upper separator
STOP = 40.0       # longer without a bin visit = stop
NAMES = {
    "CHECK1": ("In-hand check before the machine", "#0ea5e9"),
    "MACHINE": ("In the machine (load → machine check)", "#2563eb"),
    "CHECK2": ("In-hand check after the machine", "#ec4899"),
    "RAIL": ("Put rail in the bin (tray)", "#16a34a"),
    "SEP": ("Place separator", "#a855f7"),
    "TRAY": ("Cover with mesh + new empty tray", "#f59e0b"),
    "BIN": ("Bin change (full stack out, new bin)", "#dc2626"),
    "OTHER": ("Other work (away from bin and machine)", "#64748b"),
    "STOP": ("Stopped (no rail)", "#991b1b"),
}


def ts(day: str, hms: str) -> float:
    return time.mktime(time.strptime(f"{day} {hms}", "%Y-%m-%d %H:%M:%S"))


def hm(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


def zone(camera_id: int, ztype: str = "part_zone") -> list:
    with SessionLocal() as db:
        cam = db.get(models.Camera, camera_id)
        return next(z["points"] for z in cam.zones if z.get("type") == ztype)


# ------------------------------------------------------------------ signals
BED = [(0.215, 0.47), (0.33, 0.395), (0.365, 0.43), (0.25, 0.535)]  # machine bed (rail fixture) in camera 6


def operator_track(frames6: list[dict]):
    """Inspection operator = the person on the left half of camera 6, followed by position (a third person passing by
    is not picked up): box centre x and box top (larger top = bent). Plus the machine bed: share of silver (empty bed
    visible), dark (rail lying on it) and blue (operator's shirt in front of it)."""
    T, X, TOP, BW, BD, BB, last, mask = [], [], [], [], [], [], None, None
    for f in frames6:
        c = [p for p in f["p"] if (p["b"][0] + p["b"][2]) / 2 < 0.55 and p["b"][3] - p["b"][1] > 0.35]
        T.append(f["t"])
        img = read_frame(f)
        if img is not None:
            h, w = img.shape[:2]
            if mask is None or mask.shape != (h, w):
                mask = np.zeros((h, w), np.uint8)
                cv2.fillPoly(mask, [(np.asarray(BED) * [w, h]).astype(np.int32)], 255)
                mask = mask > 0
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            H, S, V = hsv[..., 0][mask], hsv[..., 1][mask], hsv[..., 2][mask]
            BW.append(float(((S < 60) & (V > 140)).mean())); BD.append(float(((V < 70) & (S < 90)).mean()))
            BB.append(float(((H > 100) & (H < 125) & (S > 90)).mean()))
        else:
            BW.append(np.nan); BD.append(np.nan); BB.append(np.nan)
        if not c:
            X.append(np.nan); TOP.append(np.nan)
            continue
        p = min(c, key=lambda p: abs((p["b"][0] + p["b"][2]) / 2 - last)) if last is not None else max(c, key=lambda p: p["b"][3] - p["b"][1])
        last = (p["b"][0] + p["b"][2]) / 2
        X.append(last); TOP.append(p["b"][1])
    return np.array(T), np.array(X), np.array(TOP), np.array(BW), np.array(BD), np.array(BB)


def bin_signal(frames7: list[dict], poly: list):
    """Camera 7 per frame: motion, dark share (rails) and blue share (bin in place) inside the bin zone."""
    T, M, D, Bl, mask, prev = [], [], [], [], None, None
    for f in frames7:
        img = read_frame(f)
        if img is None:
            continue
        img = cv2.resize(img, (320, 180))
        if mask is None:
            mask = np.zeros((180, 320), np.uint8)
            cv2.fillPoly(mask, [(np.asarray(poly) * [320, 180]).astype(np.int32)], 255)
            mask = mask > 0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        T.append(f["t"])
        M.append(float((cv2.absdiff(g, prev) > 30)[mask].mean()) if prev is not None else 0.0)
        D.append(float((hsv[..., 2] < 70)[mask].mean()))
        Bl.append(float(((hsv[..., 0] > 95) & (hsv[..., 0] < 130) & (hsv[..., 1] > 120) & (hsv[..., 2] > 70))[mask].mean()))
        prev = g
    return np.array(T), np.array(M), np.array(D), np.array(Bl)


def baseline(T, D, win=3.0):
    out, j0 = np.empty(len(D)), 0
    for i in range(len(D)):
        while T[i] - T[j0] > win:
            j0 += 1
        out[i] = np.percentile(D[j0:i + 1], 25)
    return out


def tray_drops(T, base):
    out, last = [], -1e9
    for i in range(len(T)):
        j = np.searchsorted(T, T[i] - 10.0)
        if base[j:i + 1].max() - base[i] <= 0.06 or T[i] - last <= 25:
            continue
        k = np.searchsorted(T, T[i] + 6.0)
        if k < len(T) and base[i:k + 1].max() - base[i] > 0.05:
            continue
        out.append(float(T[i])); last = T[i]
    return out


# ------------------------------------------------------------------ breakup
class Breakup:
    def __init__(self, T6, X6, TOP6, BW, BD, BB, T7, M7, D7, B7):
        self.T6, self.X6, self.TOP6, self.T7, self.M7, self.D7, self.B7 = T6, X6, TOP6, T7, M7, D7, B7
        self.BW, self.BD, self.BB = BW, BD, BB

    def machine_window(self, ret: float, nxt: float) -> tuple[float, float]:
        """Rail into the machine (load) and out of it (unload) between coming back from the bin and the next bin visit.
        load   = rail seen lying on the bed (dark on the silver bed) or the operator standing upright in front of the bed;
        unload = last moment he still stands upright at the machine before turning to the bin with the rail.
        Checked against the video: load +-1.7 s, unload +-0.6 s."""
        idx = np.where((self.T6 > ret) & (self.T6 < nxt))[0]
        load, run = None, 0
        for i in idx:
            if self.T6[i] - ret < 0.6:
                continue
            if self.BD[i] >= 0.18 and 0.12 <= self.BW[i] <= 0.38 and self.BB[i] < 0.2:
                load = float(self.T6[i]); break
            run = run + 1 if (self.X6[i] < 0.41 and self.TOP6[i] <= 0.06) else 0
            if run >= 2:
                load = float(self.T6[i - 1]); break
        cand = [i for i in idx if self.T6[i] >= nxt - 4.0 and self.TOP6[i] <= 0.075 and self.X6[i] >= 0.38]
        unload = float(self.T6[cand[-1]]) + 0.2 if cand else nxt - 1.0
        if load is None:
            load = ret + 0.6
        unload = min(max(unload, load + 0.5), nxt)
        return load, unload

    def near(self, t: float) -> bool:
        i = int(np.argmin(np.abs(self.T6 - t)))
        if abs(self.T6[i] - t) > 0.8 or np.isnan(self.X6[i]):
            return False
        # at the bin he stands left of the machine (upright e.g. fetching a tray, or bent over it); bent further right = other work
        return self.X6[i] < NEAR_X or (self.TOP6[i] > 0.13 and self.X6[i] < 0.40)

    def visits(self) -> list[list[float]]:
        runs, s, last = [], None, None
        for t, m in zip(self.T7, self.M7):
            if m > MOTION and self.near(t):
                if s is None or t - last > 1.2:
                    if s is not None:
                        runs.append([s, last])
                    s = t
                last = t
        if s is not None:
            runs.append([s, last])
        runs = [[a - 0.2, b + 0.4] for a, b in runs if b - a >= 0.3]
        out: list = []
        for r in runs:
            gap = r[0] - out[-1][1] if out else 1e9
            if gap < 1.5 or (gap < JOIN and all(self.near(t) for t in np.arange(out[-1][1], r[0], 0.35))):
                out[-1][1] = r[1]
            else:
                out.append(r)
        bent = lambda a, b: int(np.sum(np.nan_to_num(self.TOP6[(self.T6 >= a - 0.5) & (self.T6 <= b + 0.5)], nan=0) > 0.15))  # noqa: E731
        return [v for v in out if bent(*v) >= 2 and v[1] - v[0] >= 1.1]  # bin work = bending over the bin

    def run(self) -> dict:
        base = baseline(self.T7, self.D7)
        drops = tray_drops(self.T7, base)
        vis = self.visits()
        kinds = []
        for a, b in vis:
            m = (self.T7 >= b) & (self.T7 <= b + 5)
            post = float(np.median(base[m])) if m.any() else 1.0
            drop = next((d for d in drops if a - 3 <= d <= b + 3), None)
            if drop is not None and post <= 0.14:  # a new empty tray is in view after this visit
                k = np.where((self.T7 >= a) & (self.T7 <= b) & (base <= post + 0.02))[0]
                tt = float(self.T7[k[0]]) if len(k) else (a + b) / 2
                absent = int(np.sum((self.T7 >= a) & (self.T7 <= b) & (self.B7 < 0.08)))
                kinds.append(("TRAYV", a, b, tt, absent >= 6))
            elif b - a > LONG:
                kinds.append(("SEPV", a, b, None, False))
            else:
                kinds.append(("RAILV", a, b, None, False))
        rail_med = float(np.median([b - a for k, a, b, _, _ in kinds if k == "RAILV"])) if any(k == "RAILV" for k, *_ in kinds) else 2.0

        segs: list[dict] = []
        rails, trays, seps = [], [], []
        for k, a, b, tt, is_bin in kinds:
            r1 = min(a + rail_med, (tt if tt else b))
            rails.append({"t0": a, "t1": b if k == "RAILV" else r1, "kind": k})
            segs.append({"code": "RAIL", "t0": a, "t1": b if k == "RAILV" else r1})
            if k == "SEPV":
                segs.append({"code": "SEP", "t0": r1, "t1": b})
                seps.append({"t0": r1, "t1": b, "where": "upper (mid-tray)"})
            elif k == "TRAYV":
                segs.append({"code": "BIN" if is_bin else "TRAY", "t0": r1, "t1": max(r1, tt)})
                segs.append({"code": "SEP", "t0": max(r1, tt), "t1": b})
                trays.append({"t0": r1, "t1": max(r1, tt), "bin": is_bin})
                seps.append({"t0": max(r1, tt), "t1": b, "where": "in the new tray"})
        # time between visits: inspection, other work, stops
        cycles = []
        for i in range(len(kinds) - 1):
            a_end, nxt = kinds[i][2], kinds[i + 1][1]
            gap = nxt - a_end
            if gap > STOP:
                segs.append({"code": "STOP", "t0": a_end, "t1": nxt})
                continue
            other = self.other(a_end, nxt)
            load, unload = self.machine_window(a_end, nxt)
            parts = [("CHECK1", a_end, load), ("MACHINE", load, unload), ("CHECK2", unload, nxt)]
            for code, x0, x1 in parts:  # other work (bent far right) cuts into these parts
                cur = x0
                for o0, o1 in other:
                    if o1 <= cur or o0 >= x1:
                        continue
                    segs.append({"code": code, "t0": cur, "t1": max(cur, o0)})
                    segs.append({"code": "OTHER", "t0": max(cur, o0), "t1": min(o1, x1)})
                    cur = min(o1, x1)
                segs.append({"code": code, "t0": cur, "t1": x1})
            ov = lambda x0, x1: sum(max(0.0, min(o1, x1) - max(o0, x0)) for o0, o1 in other)  # noqa: E731
            k, a, b = kinds[i][0], kinds[i][1], kinds[i][2]
            cycles.append({"start": a, "end": nxt, "sec": nxt - a, "inspect": gap - sum(o1 - o0 for o0, o1 in other),
                           "check1": (load - a_end) - ov(a_end, load), "machine": (unload - load) - ov(load, unload),
                           "check2": (nxt - unload) - ov(unload, nxt),
                           "place": (b - a) if k == "RAILV" else rail_med, "other": sum(o1 - o0 for o0, o1 in other),
                           "extra": 0.0 if k == "RAILV" else (b - a) - rail_med,
                           "note": {"RAILV": "", "SEPV": "upper separator", "TRAYV": "new tray"}[k] + (" + other work" if other else "")})
        segs.sort(key=lambda s: s["t0"])
        return {"segments": [s for s in segs if s["t1"] - s["t0"] > 0.05], "rails": rails, "trays": trays, "seps": seps,
                "cycles": cycles, "rail_med": rail_med, "kinds": kinds}

    def other(self, a: float, b: float) -> list[tuple[float, float]]:
        """Bent over far from the bin (right of the machine) for >= 2 s: other work."""
        m = (self.T6 > a) & (self.T6 < b)
        T, X, TOP = self.T6[m], self.X6[m], self.TOP6[m]
        flag = (np.nan_to_num(TOP, nan=0) > 0.15) & (np.nan_to_num(X, nan=0) > 0.42)
        out, s, last = [], None, None
        for t, f in zip(T, flag):
            if f:
                s = t if s is None else s
                last = t
            elif s is not None and t - last > 1.0:
                if last - s >= 2.0:
                    out.append((s, last + 0.35))
                s = None
        if s is not None and last - s >= 2.0:
            out.append((s, last + 0.35))
        return out


def stats(R: dict, span: float) -> dict:
    med = lambda v: float(np.median(v)) if len(v) else 0.0  # noqa: E731
    q = lambda v, p: [round(float(x), 1) for x in np.percentile(v, p)] if len(v) else [0, 0]  # noqa: E731
    cyc = R["cycles"]
    plain = [c for c in cyc if not c["note"]]
    tot = {k: sum(s["t1"] - s["t0"] for s in R["segments"] if s["code"] == k) for k in NAMES}
    sep_mid = [s["t1"] - s["t0"] for s in R["seps"] if s["where"].startswith("upper")]
    sep_new = [s["t1"] - s["t0"] for s in R["seps"] if s["where"].startswith("in the new")]
    tray = [t["t1"] - t["t0"] for t in R["trays"] if not t["bin"]]
    binc = [t["t1"] - t["t0"] for t in R["trays"] if t["bin"]]
    n_tray = max(1, len(R["trays"]))
    covered = sum(tot.values())
    return {
        "rails": len(R["rails"]), "rails_per_hour": round(len(R["rails"]) / (span / 3600)),
        "inspect_med": round(med([c["inspect"] for c in cyc]), 1), "inspect_q": q([c["inspect"] for c in cyc], [10, 90]),
        "check1_med": round(med([c["check1"] for c in cyc]), 1), "check1_q": q([c["check1"] for c in cyc], [10, 90]),
        "machine_med": round(med([c["machine"] for c in cyc]), 1), "machine_q": q([c["machine"] for c in cyc], [10, 90]),
        "check2_med": round(med([c["check2"] for c in cyc]), 1), "check2_q": q([c["check2"] for c in cyc], [10, 90]),
        "check_total_med": round(med([c["check1"] + c["check2"] for c in cyc]), 1),
        "place_med": round(R["rail_med"], 1),
        "cycle_med": round(med([c["sec"] for c in plain]), 1), "cycle_q": q([c["sec"] for c in plain], [25, 75]),
        "trays": len(R["trays"]), "rails_per_tray": round(len(R["rails"]) / n_tray, 1) if R["trays"] else 0,
        "tray_med": round(med(tray), 1), "bin_n": len(binc), "bin_med": round(med(binc), 1),
        "sep_mid_med": round(med(sep_mid), 1), "sep_mid_n": len(sep_mid),
        "sep_new_med": round(med(sep_new), 1), "sep_new_n": len(sep_new),
        "sep_per_tray": round((sum(sep_mid) + sum(sep_new)) / n_tray, 1) if R["trays"] else round(med(sep_mid), 1),
        "share": {k: round(100 * v / span, 1) for k, v in tot.items()},
        "unaccounted": round(100 * max(0.0, span - covered) / span, 1),
        "stops": [(s["t0"], s["t1"]) for s in R["segments"] if s["code"] == "STOP"],
    }


# ------------------------------------------------------------------ video
def write_video(frames6, frames7, t0, t1, segs, cycles, path) -> list[float]:
    """Camera 6 and 7 side by side on one clock (3 frames / s) with the current activity and timers."""
    W, H, step = 480, 270, 1 / 3
    times = list(np.arange(t0, t1, step))
    T6, T7 = np.array([f["t"] for f in frames6]), np.array([f["t"] for f in frames7])
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP90"), 3.0, (2 * W, H + 56))
    last: dict = {}

    def pic(frames, T, t, key):
        if not len(T):
            return np.zeros((H, W, 3), np.uint8)
        i = int(np.argmin(np.abs(T - t)))
        if abs(T[i] - t) > 1.5:
            return np.zeros((H, W, 3), np.uint8)
        if last.get(key, (None,))[0] != i:
            img = read_frame(frames[i])
            last[key] = (i, cv2.resize(img, (W, H)) if img is not None else np.zeros((H, W, 3), np.uint8))
        return last[key][1]

    for t in times:
        a, b = pic(frames6, T6, t, 6).copy(), pic(frames7, T7, t, 7).copy()
        cv2.putText(a, "Cam 6: inspection", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(b, "Cam 7: bin / tray (top view)", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        img = np.vstack([np.zeros((56, 2 * W, 3), np.uint8), np.hstack([a, b])])
        s = next((x for x in segs if x["t0"] <= t < x["t1"]), None)
        c = next((x for x in cycles if x["start"] <= t < x["end"]), None)
        head = hm(t) + (f"   Rail {c['n']}   {t - c['start']:4.1f}s / {c['sec']:.1f}s" if c else "")
        cv2.putText(img, head, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        if s:
            col = tuple(int(NAMES[s["code"]][1][q:q + 2], 16) for q in (5, 3, 1))
            cv2.rectangle(img, (10, 32), (26, 50), col, -1)
            cv2.putText(img, f"{NAMES[s['code']][0][:62]}  {t - s['t0']:.1f}s", (32, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        vw.write(img)
    vw.release()
    return times


# ------------------------------------------------------------------ report
def analyse_window(t0: float, t1: float):
    f6, f7 = load_frames(INSPECTION_CAM, t0, t1), load_frames(BIN_CAM, t0, t1)
    if len(f6) < 200 or len(f7) < 200:
        return None
    T6, X6, TOP6, BW, BD, BB = operator_track(f6)
    T7, M7, D7, B7 = bin_signal(f7, zone(BIN_CAM))
    R = Breakup(T6, X6, TOP6, BW, BD, BB, T7, M7, D7, B7).run()
    return f6, f7, R


def build(t0: float, t1: float, v0: float, v1: float, auto: bool) -> Path | None:
    got = analyse_window(t0, t1)
    if got is None:
        print("not enough recording"); return None
    f6, f7, R = got
    if len(R["rails"]) < 20:
        print("too few rails (line stopped?)"); return None
    S = stats(R, t1 - t0)
    print(json.dumps({k: v for k, v in S.items() if k != "stops"}, indent=1))

    segs = [dict(s, t0=max(s["t0"], v0), t1=min(s["t1"], v1)) for s in R["segments"] if s["t1"] > v0 and s["t0"] < v1]
    vcyc = [dict(c) for c in R["cycles"] if c["start"] >= v0 and c["end"] <= v1]
    for n, c in enumerate(vcyc, start=1):
        c["n"] = n
        c["normal"] = not c["note"] and c["sec"] < 1.5 * max(1.0, S["cycle_med"])

    day = datetime.fromtimestamp(v0).strftime("%Y-%m-%d")
    name = (f"auto_final_{datetime.fromtimestamp(v0):%Y%m%d_%H%M}" if auto else f"final-inspection-bin_{datetime.fromtimestamp(v0):%Y%m%d_%H%M}")
    out = settings.reports_dir / (name + ".tmp")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    vf6, vf7 = [f for f in f6 if v0 <= f["t"] <= v1], [f for f in f7 if v0 <= f["t"] <= v1]
    vtimes = write_video(vf6, vf7, v0, v1, segs, vcyc, out / "video.webm")
    (out / "timeline.json").write_text(json.dumps(timeline(vtimes, segs, vcyc, NAMES), separators=(",", ":")), encoding="utf-8")
    vt = lambda t: max(0.0, t - v0)  # noqa: E731  video runs on the wall clock

    shots = []
    for code in ("CHECK1", "MACHINE", "CHECK2", "RAIL", "SEP", "TRAY", "BIN", "STOP"):
        lst = [s for s in R["segments"] if s["code"] == code and s["t1"] - s["t0"] >= 1.0]
        x = next((s for s in lst if v0 <= s["t0"] <= v1), None) or (lst[len(lst) // 2] if lst else None)
        if not x:
            continue
        tm, imgs = (x["t0"] + x["t1"]) / 2, []
        for frames in (f6, f7):
            fr = min(frames, key=lambda f: abs(f["t"] - tm))
            im = read_frame(fr)
            imgs.append(cv2.resize(im, (320, 180)) if im is not None else np.zeros((180, 320, 3), np.uint8))
        cv2.imwrite(str(out / "frames" / f"{code}.jpg"), np.hstack(imgs), [cv2.IMWRITE_JPEG_QUALITY, 80])
        shots.append((code, x))

    for c in R["cycles"]:
        c["flag"] = "normal" if not c["note"] and c["sec"] < 1.5 * max(1.0, S["cycle_med"]) else "long"
        c["el"] = {"RAIL": c["place"], "EXTRA": c["extra"] if c["extra"] > 0.05 else None, "CHECK1": c["check1"], "MACHINE": c["machine"],
                   "CHECK2": c["check2"], "OTHER": c["other"] if c["other"] > 0.05 else None}
    elements = [("RAIL", NAMES["RAIL"][0], NAMES["RAIL"][1]), ("EXTRA", "Separator / new tray (same bin visit)", NAMES["SEP"][1]),
                ("CHECK1", NAMES["CHECK1"][0], NAMES["CHECK1"][1]), ("MACHINE", NAMES["MACHINE"][0], NAMES["MACHINE"][1]),
                ("CHECK2", NAMES["CHECK2"][0], NAMES["CHECK2"][1]), ("OTHER", NAMES["OTHER"][0], NAMES["OTHER"][1])]
    (out / "cycles.json").write_text(json.dumps(variation_data(elements, R["cycles"], v0, v1), separators=(",", ":")), encoding="utf-8")

    esc = html.escape
    rows = "".join(
        f"<tr{'' if c['normal'] else ' class=bad'} onclick=\"seek({vt(c['start']):.2f})\"><td class=n>{c['n']}</td><td class=num>{hm(c['start'])}</td>"
        f"<td class=num><b>{c['sec']:.1f}s</b></td><td class=num>{c['place']:.1f}</td><td class=num>{c['extra']:.1f}</td>"
        f"<td class=num>{c['check1']:.1f}</td><td class=num>{c['machine']:.1f}</td><td class=num>{c['check2']:.1f}</td><td>{esc(c['note'] or 'Normal')}</td></tr>" for c in vcyc)
    trows = "".join(f"<tr onclick=\"seek({vt(s['t0']):.2f})\"><td class=num>{hm(s['t0'])}</td><td>{esc(s['where'])}</td><td class=num><b>{s['t1'] - s['t0']:.1f}s</b></td></tr>"
                    for s in R["seps"])
    brows = "".join(f"<tr onclick=\"seek({vt(t['t0']):.2f})\"><td class=num>{hm(t['t0'])}</td><td>{'Bin change' if t['bin'] else 'New tray'}</td>"
                    f"<td class=num><b>{t['t1'] - t['t0']:.1f}s</b></td></tr>" for t in R["trays"])
    srows = "".join(f"<tr onclick=\"seek({vt(a):.2f})\"><td class=num>{hm(a)}</td><td class=num><b>{b - a:.0f}s</b></td></tr>" for a, b in S["stops"])
    shot_html = "".join(f"<figure><img src=\"frames/{k}.jpg\" alt=\"\"><figcaption><span class=dot style=\"background:{NAMES[k][1]}\"></span>"
                        f"{esc(NAMES[k][0])} – {hm(x['t0'])}, {x['t1'] - x['t0']:.1f}s</figcaption></figure>" for k, x in shots)
    legend = "".join(f'<span><span class=dot style="background:{v[1]}"></span>{esc(v[0])}</span>' for v in NAMES.values())
    sh = S["share"]
    split = "".join(f'<i style="width:{sh[k]}%;background:{NAMES[k][1]}" title="{esc(NAMES[k][0])} {sh[k]}%"></i>' for k in NAMES if sh[k] > 0)
    short = {"CHECK1": "Check before", "MACHINE": "In machine", "CHECK2": "Check after", "RAIL": "Put in bin",
             "SEP": "Separator", "TRAY": "Mesh + tray", "BIN": "Bin change", "OTHER": "Other work", "STOP": "Stopped"}
    split_legend = "".join(f'<span><span class=dot style="background:{NAMES[k][1]}"></span>{esc(short[k])} {sh[k]}%</span>' for k in NAMES if sh[k] > 0)
    bin_work = sh["SEP"] + sh["TRAY"] + sh["BIN"]
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Final inspection + bin</title>
<style>
:root{{--bg:#f8fafc;--panel:#fff;--ink:#0f172a;--ink2:#475569;--edge:#e2e8f0;--bad:#fef2f2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--panel:#111827;--ink:#e5e7eb;--ink2:#9ca3af;--edge:#1f2937;--bad:#3b1111}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}} main{{max-width:1180px;margin:0 auto;padding:16px}}
h1{{font-size:20px;margin:4px 0}} h2{{font-size:16px;margin:22px 0 8px}} .sub{{color:var(--ink2)}}
.card{{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:14px;margin:12px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}} .kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--ink2);font-size:12px}}
video{{width:100%;background:#000;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--edge);text-align:left}} th{{font-size:12px;color:var(--ink2)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} td.n{{color:var(--ink2)}} tr.bad{{background:var(--bad)}} tbody tr{{cursor:pointer}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}} ul,ol{{margin:6px 0;padding-left:20px}} li{{margin:4px 0}}
figure{{margin:0}} figure img{{width:100%;border-radius:6px}} .shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.three{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}} .scroll{{max-height:420px;overflow:auto}}
.split{{display:flex;height:22px;border-radius:5px;overflow:hidden;margin:8px 0;background:var(--edge)}} .split i{{display:block;height:100%}}
</style>{PLAYER_HEAD}</head><body><main>
<h1>Final inspection + bin (tray / separator) timing</h1>
<div class=sub>Camera 6 (inspection) + camera 7 (bin, top view) · {day} · statistics {hm(t0)}–{hm(t1)} ({(t1 - t0) / 60:.0f} min) · video {hm(v0)}–{hm(v1)}{' · automatic report (' + datetime.now().strftime('%H:%M') + ')' if auto else ''}</div>
<div class="card kpis">
<div class=kpi><b>{S['check1_med']:.1f}s</b><span>in-hand check before the machine (80 % of rails {S['check1_q'][0]}–{S['check1_q'][1]}s)</span></div>
<div class=kpi><b>{S['machine_med']:.1f}s</b><span>in the machine, load → check (80 % {S['machine_q'][0]}–{S['machine_q'][1]}s)</span></div>
<div class=kpi><b>{S['check2_med']:.1f}s</b><span>in-hand check after the machine (80 % {S['check2_q'][0]}–{S['check2_q'][1]}s)</span></div>
<div class=kpi><b>{S['place_med']:.1f}s</b><span>put rail in the bin (tray)</span></div>
<div class=kpi><b>{S['cycle_med']:.1f}s</b><span>normal rail cycle (middle 50 %: {S['cycle_q'][0]}–{S['cycle_q'][1]}s)</span></div>
<div class=kpi><b>{S['rails']}</b><span>rails ({S['rails_per_hour']}/h) · in-hand checks ~{S['check_total_med']:.1f}s per rail</span></div>
<div class=kpi><b>{S['sep_mid_med']:.1f}s</b><span>upper separator, mid-tray ({S['sep_mid_n']}×)</span></div>
<div class=kpi><b>{S['sep_new_med']:.1f}s</b><span>separator in a new tray ({S['sep_new_n']}×)</span></div>
<div class=kpi><b>{S['tray_med']:.1f}s</b><span>mesh + new tray ({S['trays'] - S['bin_n']}×)</span></div>
<div class=kpi><b>~{S['rails_per_tray']:.0f}</b><span>rails per tray · separators ~{S['sep_per_tray']:.0f}s per tray</span></div>
</div>
<div class=card><b>Where the operator's time went ({(t1 - t0) / 60:.0f} min)</b>
<div class=split>{split}</div><div class=legend>{split_legend}{f'<span>not assigned {S["unaccounted"]}%</span>' if S['unaccounted'] > 0.5 else ''}</div></div>
<div class=card><video id=v src="video.webm" controls preload=metadata></video><div class=legend>{legend}</div>
<div class=sub>Left camera 6, right camera 7. Overlay: clock, rail number and timer, current element. Click a table row to jump there.</div></div>
{VARIATION_HTML}
<h2>Method (built from frame-by-frame video review)</h2><div class=card><ol>
<li><b>In-hand check before the machine</b>: back from the bin, the machine bed is empty; he checks the next rail in his hands until it goes onto the bed.</li>
<li><b>In the machine</b>: rail on the bed → machine check, until he lifts it off (camera 6: dark rail on the bed, or operator upright in front of it).</li>
<li><b>In-hand check after the machine</b>: from lifting the rail off the bed until it goes into the bin; he looks at it while turning.</li>
<li>Camera 6 sees him from behind and his hands are often hidden: load is accurate to ±1.7 s, unload to ±0.6 s (8 cycles checked against video).</li>
<li><b>Put rail in the bin</b>: one rail per trip; camera 7 shows hands + rail in the tray (~2 s).</li>
<li><b>Upper separator</b>: after 5 rails of a tray he lays the white separator (comb); that bin visit takes ~7–9 s; separator = visit − rail time.</li>
<li><b>Full tray</b> (~10 rails): mesh folded over → empty tray on top (camera 7: rails covered) → separators set in the new tray.</li>
<li><b>Bin change</b>: the bin leaves camera 7 (stack onto the rollers, new bin + plastic sheet).</li>
<li><b>Other work</b>: bent over to the right, away from bin and machine. <b>Stopped</b>: no rail for over {STOP:.0f} s.</li>
</ol><div class=sub>Validated on a 9 frames/s capture (10 Oct, 00:22–00:35): 48/48 rails, 5/5 tray changes, 4/4 upper separators.</div></div>
<div class=shots>{shot_html}</div>
<h2>Every rail in the video</h2><div class="card scroll"><table><thead><tr><th>#</th><th>Start</th><th>Cycle</th><th>Put in bin</th><th>Separator / tray</th><th>Check before</th><th>In machine</th><th>Check after</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class=three>
<div><h2>Separators</h2><div class="card scroll"><table><thead><tr><th>Time</th><th>Where</th><th>Duration</th></tr></thead><tbody>{trows}</tbody></table></div></div>
<div><h2>New tray / bin change</h2><div class="card scroll"><table><thead><tr><th>Time</th><th>What</th><th>Duration</th></tr></thead><tbody>{brows}</tbody></table></div></div>
<div><h2>Stops</h2><div class="card scroll"><table><thead><tr><th>Time</th><th>Duration</th></tr></thead><tbody>{srows or '<tr><td colspan=2>None</td></tr>'}</tbody></table></div></div>
</div>
<h2>Findings</h2><div class=card><ul>
<li>Per rail: check before ~{S['check1_med']:.1f}s → in machine ~{S['machine_med']:.1f}s → check after ~{S['check2_med']:.1f}s → put in bin ~{S['place_med']:.1f}s.</li>
<li>In-hand checks total ~{S['check_total_med']:.1f}s per rail; with the machine check he spends ~{S['inspect_med']:.1f}s at the machine.</li>
<li>Separators twice per tray: upper ~{S['sep_mid_med']:.1f}s, new tray ~{S['sep_new_med']:.1f}s; ~{S['rails_per_tray']:.0f} rails per tray, so ~{S['sep_per_tray'] / max(1, S['rails_per_tray']):.1f}s of separator work per rail.</li>
<li>Mesh + new tray ~{S['tray_med']:.1f}s per tray.</li>
<li>Time share: separator + tray + bin change {bin_work:.0f}%, in-hand checks {sh['CHECK1'] + sh['CHECK2']:.0f}%, in machine {sh['MACHINE']:.0f}%, put in bin {sh['RAIL']:.0f}%{f", other work {sh['OTHER']:.0f}%" if sh['OTHER'] else ''}{f", stopped {sh['STOP']:.0f}%" if sh['STOP'] else ''}.</li>
</ul></div>
<div class=sub>From the camera 6 and 7 recordings (~3 frames/s).</div>
</main>{PLAYER_BODY}{CHARTS_BODY}</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    meta = {"title": "Final inspection + bin (tray / separator) timing", "subtitle": "Cameras 6 + 7 · inspection, put in bin, separators, mesh + tray, bin change",
            "camera_id": INSPECTION_CAM, "cameras": [INSPECTION_CAM, 7], "station_id": STATION_ID, "auto": auto, "date": day, "window": f"{hm(v0)} – {hm(v1)}",
            "cycles": len(vcyc), "median_cycle": S["cycle_med"],
            "highlights": [f"Check before ~{S['check1_med']:.1f}s + machine ~{S['machine_med']:.1f}s + check after ~{S['check2_med']:.1f}s + bin ~{S['place_med']:.1f}s ({S['rails_per_hour']}/h)",
                           f"Separators: upper ~{S['sep_mid_med']:.1f}s, new tray ~{S['sep_new_med']:.1f}s (~{S['sep_per_tray']:.0f}s per tray)",
                           f"Mesh + new tray ~{S['tray_med']:.1f}s; ~{S['rails_per_tray']:.0f} rails per tray"]}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "data.json").write_text(json.dumps({"stats": S, "window": [t0, t1], "video": [v0, v1], "segments": R["segments"],
                                               "seps": R["seps"], "trays": R["trays"]}, indent=1), encoding="utf-8")
    final = settings.reports_dir / name
    publish(out, final)
    print("report", final)
    return final


def main() -> None:
    if sys.argv[1:2] == ["--auto"]:
        recent = load_frames(INSPECTION_CAM, time.time() - 900, time.time())
        if not recent:
            print("no recent recording"); sys.exit(1)
        t1 = recent[-1]["t"] - 2
        res = build(t1 - 3600, t1, t1 - 330, t1, auto=True)
    else:
        a, b, va, vb = sys.argv[1:5]
        day = sys.argv[5] if len(sys.argv) > 5 else datetime.now().strftime("%Y-%m-%d")
        res = build(ts(day, a), ts(day, b), ts(day, va), ts(day, vb), auto=False)
    sys.exit(0 if res else 1)


if __name__ == "__main__":
    main()
