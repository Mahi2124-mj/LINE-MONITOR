"""Cycles of the validated step detectors (station_breakup.py) for a time window, as JSON for the live cycle count.

usage: detector_feed.py <t0 epoch> <t1 epoch> <key> [<key> ...]
prints {"cycles": {key: [{start, end, sec, work, motion, wait, stop}]}, "errors": {key: message}}

Run by app.services.detector_feed every few minutes on the last minutes of the recording; the keys of one camera are
run together so its frames are read only once. Times per cycle are the operator's: work = his loop time (machine waits
inside his loop included, they set his pace), motion = walking / carrying, wait = waiting for a part or another person,
and for a line stop everything beyond the median cycle."""
import json
import os
import statistics as stat
import sys
import traceback

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import station_breakup as sb  # noqa: E402

# step codes that are not hand work (everything else in a cycle is): per detector key. motion = walking / carrying,
# wait = waiting for a part or a person, machine = he stands at a machine until it finishes (counted as his work time
# in the cycle split: it sets his pace; shown apart on the Movement & waste page)
KINDS = {
    "yur": {},
    "yhs": {"WALK": "motion", "BACK": "motion", "ON": "machine", "END": "machine"},
    "yxl": {"WALK": "motion"},
    "yg1": {"START": "motion"},
    "yg2": {},
    "ylr": {"CARRY": "motion", "WALK": "motion"},
    "ysr": {},
    "ysf": {"BACK": "wait"},
    "yml": {"FETCH": "motion"},
    "ymm": {"BACK": "motion", "WAIT": "wait"},
    "yfi": {"AFTER": "motion", "WAIT": "wait", "MACHINE": "machine"},
    # YWD SS line (camera 22): back at the front tray beyond the turn = waiting for the next taped rail
    "yjc": {"BACK": "wait"},
    "ytp": {},
}

_frames: dict = {}
_load = sb.load_frames


def _cached_load(cam, t0, t1):
    """the detectors of one camera all read the same window: decode it once"""
    if (cam, t0, t1) not in _frames:
        _frames[(cam, t0, t1)] = _load(cam, t0, t1)
    return _frames[(cam, t0, t1)]


sb.load_frames = _cached_load


def cycles_of(key: str, t0: float, t1: float) -> list[dict]:
    st = sb.STATIONS[key]()
    got = sb.analyse(st, t0, t1)
    if got is None:
        return []
    _, cycles = got
    if not cycles:
        return []
    sb.classify(cycles)
    med = stat.median(c["sec"] for c in cycles)
    kinds = KINDS.get(key, {})
    out = []
    for c in cycles:
        motion = sum(v for code, v in c["el"].items() if code in c["have"] and kinds.get(code) == "motion")
        wait = sum(v for code, v in c["el"].items() if code in c["have"] and kinds.get(code) == "wait")
        if c["stop"]:
            wait = max(wait, c["sec"] - med)
        motion = min(motion, max(0.0, c["sec"] - wait))
        out.append({"start": round(c["start"], 3), "end": round(c["end"], 3), "sec": round(c["sec"], 2),
                    "work": round(max(0.0, c["sec"] - motion - wait), 2), "motion": round(motion, 2), "wait": round(wait, 2),
                    "stop": bool(c["stop"]), **({"rivet": bool(c["rivet"])} if c.get("rivet") is not None else {}),
                    "el": {code: round(v, 2) for code, v in c["el"].items() if code in c["have"] and v > 0.005},
                    "seg": [[sg["code"], round(sg["t0"] - c["start"], 2), round(sg["t1"] - sg["t0"], 2)] for sg in c.get("segments", [])
                            if sg["t1"] - sg["t0"] > 0.005]})
    return out


def main() -> None:
    t0, t1, keys = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3:]
    res: dict = {"cycles": {}, "errors": {}, "meta": {}}
    for key in keys:
        if key not in sb.STATIONS:
            res["errors"][key] = "no such detector"
            continue
        kinds = KINDS.get(key, {})
        res["meta"][key] = {code: [label, {"motion": "walk"}.get(kinds.get(code, "work"), kinds.get(code, "work")), color]
                            for code, (label, color) in sb.STATIONS[key].NAMES.items()}
        try:
            res["cycles"][key] = cycles_of(key, t0, t1)
        except Exception as e:  # one broken detector must not stop the others
            res["errors"][key] = f"{type(e).__name__}: {e}"
            traceback.print_exc(file=sys.stderr)
    sys.stdout.write(json.dumps(res))


if __name__ == "__main__":
    main()
