"""Cycle + segment breakup of the Rail Assy #01/#02 operator from a recorded window of camera 3.
usage: breakup.py <HH:MM:SS start> <HH:MM:SS end> <out_dir>"""
import json, sqlite3, sys, statistics as S, datetime as dt
from pathlib import Path
import numpy as np, cv2, rec

a, b, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
t0, t1 = rec.ts(a), rec.ts(b)
db = sqlite3.connect(r"file:C:\Users\DX-ADMIN\Pictures\LIne monitoring\backend\data\line_monitor.db?mode=ro", uri=True)
fixture = [np.array(z["points"], np.float32) for z in json.loads(db.execute("select zones from cameras where id=3").fetchone()[0]) if z["type"] == "part_zone"][0]
idx = rec.index(3, t0, t1)

LABELS = {
    "M1": ("Machine #01 par kaam (rail nikalna / parts load)", "#2563eb"),
    "W12": ("Rail lekar #02 tak chalna", "#f59e0b"),
    "M2": ("Machine #02 par kaam (rail + parts load / nikalna)", "#16a34a"),
    "W21": ("Wapas #01 tak chalna", "#fbbf24"),
    "AWAY": ("#01/#02 se door (daayein side / camera se bahar)", "#dc2626"),
}


def feet(p):
    bx = p["b"]
    return ((bx[0] + bx[2]) / 2, bx[3])


def place(f):
    x, y = f
    if y >= 0.88 and x <= 0.52:
        return "M1"
    if y <= 0.82 and x > 0.52:
        return "M2"
    return "WALK"


# ---- follow operator A (works #01/#02). The second operator stays at the right edge (feet x > 0.74), so only
# people left of that line can be operator A; when nobody is there, A is away from his machines.
T, LOC, HIT, POS = [], [], [], []
last = None
for t, m, o, n, r in idx:
    inner = [p for p in r.get("p", []) if feet(p)[0] < 0.74]
    if not inner:
        T.append(t); LOC.append("AWAY"); HIT.append(False); POS.append(None)
        continue
    cand = min(inner, key=lambda p: np.hypot(*np.subtract(feet(p), last)) if last is not None else feet(p)[0])
    last = feet(cand)
    T.append(t); LOC.append(place(last)); POS.append(last)
    HIT.append(any(cand["k"][k][2] >= .35 and cv2.pointPolygonTest(fixture, (cand["k"][k][0], cand["k"][k][1]), False) >= 0 for k in (9, 10)))
T = np.array(T)
# walking: feet moving fast (and hands not in the #01 fixture)
SPD = np.zeros(len(T))
for i in range(1, len(T) - 1):
    if POS[i - 1] is not None and POS[i + 1] is not None:
        SPD[i] = np.hypot(*np.subtract(POS[i + 1], POS[i - 1])) / max(1e-3, T[i + 1] - T[i - 1])
for i in range(len(T)):
    if LOC[i] in ("M1", "M2") and SPD[i] > 0.22 and not HIT[i]:
        LOC[i] = "WALK"

# ---- smooth: majority of +-2 frames, then drop runs shorter than 0.8 s
L = list(LOC)
for i in range(len(L)):
    w = LOC[max(0, i - 1): i + 2]
    L[i] = max(set(w), key=w.count)


def runs_of(labels):
    rs = []
    for i, l in enumerate(labels):
        if rs and rs[-1][0] == l:
            rs[-1][2] = i
        else:
            rs.append([l, i, i])
    return rs


rs = runs_of(L)
changed = True
while changed:
    changed = False
    for k, (l, i, j) in enumerate(rs):
        if T[j] - T[i] < 0.5 and len(rs) > 1:
            nb = rs[k - 1] if k > 0 else rs[k + 1]
            for q in range(i, j + 1):
                L[q] = nb[0]
            changed = True
            break
    rs = runs_of(L)

# WALK direction: after M1 -> W12, after M2 -> W21
prev_place = None
for k, (l, i, j) in enumerate(rs):
    if l == "WALK":
        nxt = next((r[0] for r in rs[k + 1:] if r[0] != "WALK"), None)
        lab = "W12" if prev_place == "M1" and nxt != "M1" else "W21"
        for q in range(i, j + 1):
            L[q] = lab
    elif l in ("M1", "M2"):
        prev_place = l
rs = runs_of(L)

# ---- cycle start = hands reach the #01 fixture after the operator arrived at #01 from elsewhere
starts = []
for k, (l, i, j) in enumerate(rs):
    if l == "M1" and k > 0:
        first_hit = next((q for q in range(i, j + 1) if HIT[q]), i)
        starts.append(first_hit)
# segments
segments = []
for l, i, j in rs:
    e = j + 1 if j + 1 < len(T) else j
    segments.append({"code": l, "t0": float(T[i]), "t1": float(T[e])})


def cut(seg, a_, b_):
    s0, s1 = max(seg["t0"], a_), min(seg["t1"], b_)
    return {"code": seg["code"], "t0": s0, "t1": s1} if s1 - s0 > 0.05 else None


cycles = []
for c, (si, ei) in enumerate(zip(starts, starts[1:]), start=1):
    cs, ce = float(T[si]), float(T[ei])
    segs = [x for x in (cut(s, cs, ce) for s in segments) if x]
    cycles.append({"n": c, "start": cs, "end": ce, "sec": round(ce - cs, 1), "segments": segs})

med = S.median([c["sec"] for c in cycles])
med_seg = {}
for code in LABELS:
    v = [sum(s["t1"] - s["t0"] for s in c["segments"] if s["code"] == code) for c in cycles if c["sec"] <= 1.4 * med]
    med_seg[code] = round(float(np.median(v)), 1) if v else 0.0
for c in cycles:
    per = {code: round(sum(s["t1"] - s["t0"] for s in c["segments"] if s["code"] == code), 1) for code in LABELS}
    c["per"] = per
    notes = []
    if per["AWAY"] >= 3:
        notes.append(f"Operator {per['AWAY']:.0f}s #01/#02 se door raha")
    for code in ("M1", "M2", "W12", "W21"):
        if per[code] - med_seg[code] > max(2.0, 0.35 * med_seg[code]):
            notes.append(f"{LABELS[code][0]}: {per[code]:.1f}s (normal {med_seg[code]:.1f}s)")
    c["normal"] = c["sec"] <= 1.3 * med and not notes
    c["notes"] = notes or ["Normal cycle"]
    c["start_s"] = dt.datetime.fromtimestamp(c["start"]).strftime("%H:%M:%S")
    c["end_s"] = dt.datetime.fromtimestamp(c["end"]).strftime("%H:%M:%S")

# what is before the first and after the last start: not complete cycles
partial = {"before": round(float(T[starts[0]] - T[0]), 1) if starts else None,
           "after": round(float(T[-1] - T[starts[-1]]), 1) if starts else None}
json.dump({"window": [a, b], "fps": round(len(T) / (T[-1] - T[0]), 1), "cycles": cycles, "median": med, "median_seg": med_seg,
           "labels": LABELS, "partial": partial}, open(out / "data.json", "w", encoding="utf-8"), indent=1)
print(f"{len(cycles)} complete cycles, median {med}s, median segments {med_seg}")
for c in cycles:
    print(c["n"], c["start_s"], c["end_s"], c["sec"], {k: v for k, v in c["per"].items() if v}, "|", "; ".join(c["notes"]))

# ---- annotated video (whole window)
seg_at = lambda t: next((s for s in segments if s["t0"] <= t < s["t1"]), None)
cyc_at = lambda t: next((c for c in cycles if c["start"] <= t < c["end"]), None)
fps = len(T) / (T[-1] - T[0])
W, H = 640, 360
vw = cv2.VideoWriter(str(out / "video.webm"), cv2.VideoWriter_fourcc(*"VP90"), fps, (W, H))
for k, (t, m, o, n, r) in enumerate(idx):
    img = cv2.resize(rec.frame(m, o, n), (W, H))
    s, c = seg_at(t), cyc_at(t)
    if POS[k] is not None:
        cv2.circle(img, (int(POS[k][0] * W), int(min(POS[k][1], 0.99) * H)), 10, (0, 255, 255), 2)
    cv2.rectangle(img, (0, 0), (W, 64), (0, 0, 0), -1)
    clock = dt.datetime.fromtimestamp(t).strftime("%H:%M:%S")
    if c:
        head = f"{clock}   Cycle {c['n']}   {t - c['start']:5.1f}s / {c['sec']:.1f}s"
    else:
        head = f"{clock}   (cycle shuru hone se pehle / baad - adhoori cycle)"
    cv2.putText(img, head, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1, cv2.LINE_AA)
    if s:
        col = tuple(int(LABELS[s["code"]][1][q:q + 2], 16) for q in (5, 3, 1))
        cv2.rectangle(img, (10, 36), (26, 54), col, -1)
        txt = {"M1": "Machine #01 par kaam", "W12": "Rail lekar #02 tak", "M2": "Machine #02 par kaam", "W21": "Wapas #01 tak",
               "AWAY": "#01/#02 se door"}[s["code"]]
        cv2.putText(img, f"{txt}  {t - s['t0']:.1f}s", (32, 51), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    if c:  # segment bar of the current cycle
        x0 = 0
        for sg in c["segments"]:
            x1 = int((sg["t1"] - c["start"]) / c["sec"] * W)
            col = tuple(int(LABELS[sg["code"]][1][q:q + 2], 16) for q in (5, 3, 1))
            cv2.rectangle(img, (x0, H - 14), (x1, H), col, -1)
            x0 = x1
        cx = int((t - c["start"]) / c["sec"] * W)
        cv2.rectangle(img, (cx - 2, H - 20), (cx + 2, H), (255, 255, 255), -1)
    vw.write(img)
vw.release()
print("video written", (out / "video.webm").stat().st_size // 1024, "KB")
