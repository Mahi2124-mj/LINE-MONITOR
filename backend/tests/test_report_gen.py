"""Automatic report segments: an operator who works at two places (like Rail Assy #01 + #02) and walks between them."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.report_gen import analyse  # noqa: E402

FIX = [[0.2, 0.6], [0.5, 0.6], [0.5, 1.0], [0.2, 1.0]]
AREA = [[0.1, 0.2], [0.9, 0.2], [0.9, 0.99], [0.1, 0.99]]


def person(x: float, y: float, hands_at_fixture: bool) -> dict:
    k = [[x, y - 0.3, 0.9]] * 17
    k = [list(v) for v in k]
    hx, hy = (0.35, 0.8) if hands_at_fixture else (x, y - 0.2)
    k[9] = [hx, hy, 0.9]
    k[10] = [hx, hy, 0.9]
    return {"b": [x - 0.05, y - 0.5, x + 0.05, y], "c": [x, y - 0.35], "k": k}


def main() -> None:
    # cycle 25 s: 10 s at place A (fixture, front left), 1.5 s walk, 12 s at place B (back right), 1.5 s walk back
    frames, cycles, t, fps = [], [], 0.0, 5.0
    a, b = (0.35, 0.95), (0.7, 0.6)
    for n in range(8):
        c0 = t
        plan = [(10.0, a, a, True), (1.5, a, b, False), (12.0, b, b, False), (1.5, b, a, False)]
        if n == 5:  # abnormal: 20 s away
            plan.insert(3, (20.0, None, None, False))
        for dur, p0, p1, hands in plan:
            steps = int(dur * fps)
            for i in range(steps):
                if p0 is None:
                    people = []
                else:
                    f = i / steps
                    x, y = p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f
                    people = [person(x, y, hands)]
                frames.append({"t": t, "p": people, "op": 0 if people else None})
                t += 1 / fps
        cycles.append({"start": c0, "end": t})
    info = {"zones": [{"type": "part_zone", "name": "Fixture", "points": FIX}, {"type": "work_area", "points": AREA}]}
    A = analyse(info, frames, cycles)
    names = {k: v[0] for k, v in A["names"].items()}
    print("places", A["places"], names)
    print("median per segment", A["median_per"])
    for c in A["cycles"]:
        print(c["n"], c["sec"], {k: v for k, v in c["per"].items() if v}, c["notes"])
    assert len(A["places"]) == 2 and not A["machine_mode"]
    fix = next(k for k, v in names.items() if k.startswith("P") and v.startswith("Fixture"))
    other = next(k for k in names if k.startswith("P") and k != fix)
    assert 9 <= A["median_per"][fix] <= 11.5 and 11 <= A["median_per"][other] <= 13.5, A["median_per"]
    walk = sum(v for k, v in A["median_per"].items() if k.startswith("W"))
    assert 1.5 <= walk <= 4.5, walk
    bad = [c["n"] for c in A["cycles"] if not c["normal"]]
    assert bad == [6], bad
    assert 18 <= A["cycles"][5]["per"]["AWAY"] <= 21
    print("OK")


if __name__ == "__main__":
    main()
