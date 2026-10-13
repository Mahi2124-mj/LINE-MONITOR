"""End-to-end: recordings -> learn -> analysed cycles -> API (summary, list, detail, WebM clip, thumbnail,
master cycle, rename)."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LM_DATA_DIR"] = tempfile.mkdtemp(prefix="lm_api_")
os.environ["LM_RECORDINGS_DIR"] = os.path.join(os.environ["LM_DATA_DIR"], "recordings")
os.environ["LM_DB_PATH"] = os.path.join(os.environ["LM_DATA_DIR"], "t.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import analysis as A  # noqa: E402
from app.vision import synthetic  # noqa: E402

import test_elements as TE  # noqa: E402


def test_analysis_api():
    init_db()
    with SessionLocal() as db:
        line = models.Line(name="Test", takt_time_sec=20)
        db.add(line)
        db.flush()
        st = models.Station(line_id=line.id, sequence=1, name="Rail Assy m/c #01", target_cycle_sec=20)
        db.add(st)
        db.flush()
        cam = models.Camera(line_id=line.id, station_id=st.id, name="cam", source_type="simulated", source="sim", enabled=False,
                            zones=synthetic.demo_zones(), config={"record": True, "process_fps": 6})
        db.add(cam)
        db.commit()
        cam_id = cam.id
    # record into this camera's folder
    orig = TE.record.__code__
    TE_CAM = cam_id

    def record_for(minutes):
        import types
        from app.vision.worker import CameraWorker, LineMeta, StationMeta

        clock = [TE.T0]
        synthetic.time = types.SimpleNamespace(time=lambda: clock[0])
        meta = StationMeta(id=1, line_id=1, name="Rail assy", sequence=1, target_cycle_sec=20, expected_picks=2)
        info = {"id": TE_CAM, "line_id": 1, "station_id": 1, "name": "cam", "source_type": "simulated", "source": "sim",
                "zones": synthetic.demo_zones(),
                "config": {"tracker": "simulated", "process_fps": 6, "record": True, "analyzers": ["cycle_time"],
                           "sim": {"far_reach_prob": 0.15, "walk_prob": 0.1, "extra_pick_prob": 0.1}}}
        w = CameraWorker(info, {1: meta}, LineMeta(1, "L", 20))
        w.complete_cycle = lambda d: None
        assert w._open_source()
        w.source.rng.seed(7)
        w._setup_pipeline(synthetic.W, synthetic.H)
        for _ in range(int(minutes * 60 * 6)):
            clock[0] += 1 / 6
            w._process(w.source.read()[1], clock[0], 1 / 6)
        w.recorder.close()
        w.source.close()

    del orig
    record_for(15)

    model = A.learn_camera(cam_id, 60)
    assert model is not None
    c = TestClient(app)  # no lifespan: camera workers are not started
    s = c.get(f"/api/analysis/cameras/{cam_id}").json()
    print("state", s["state"], "elements", [(e["id"], e["name"], e["desc"]) for e in s["model"]["elements"]])
    print("stats", {k: s["stats"][k] for k in ("cycles", "ok", "with_issues", "avg_cycle", "best_cycle")}, "top", s["stats"]["top_issues"][:3])
    assert s["state"] == "ready" and s["stats"]["cycles"] >= 25

    cycles = c.get(f"/api/analysis/cameras/{cam_id}/cycles").json()
    bad = next(x for x in cycles if x["status"] == "issues")
    d = c.get(f"/api/analysis/cycles/{bad['id']}").json()
    print("cycle", d["cycle_sec"], [i["text"] for i in d["issues"]])
    assert d["issues"] and d["elements"]

    r = c.get(f"/api/analysis/cycles/{bad['id']}/clip.webm")
    print("clip", r.status_code, r.headers.get("content-type"), len(r.content), "bytes")
    assert r.status_code == 200 and r.headers["content-type"] == "video/webm" and len(r.content) > 10_000

    t = c.get(f"/api/analysis/cameras/{cam_id}/elements/1/thumb.jpg")
    assert t.status_code == 200 and t.content[:2] == b"\xff\xd8"

    good = next(x for x in cycles if x["status"] == "ok")
    assert c.post(f"/api/analysis/cycles/{good['id']}/master").status_code == 200
    s2 = c.get(f"/api/analysis/cameras/{cam_id}").json()
    assert s2["model"]["standard"]["source"] == "master" and s2["model"]["standard"]["master_cycle_id"] == good["id"]

    assert c.put(f"/api/analysis/cameras/{cam_id}/elements/3", json={"name": "Pick housing from bin A"}).status_code == 200
    renamed = [x for x in c.get(f"/api/analysis/cameras/{cam_id}/cycles").json() if any(e["id"] == 3 for e in x["elements"])]
    d2 = c.get(f"/api/analysis/cycles/{renamed[0]['id']}").json()
    names = {e["name"] for e in d2["elements"]}
    print("after rename:", sorted(names))
    assert "Pick housing from bin A" in names
    # learning again keeps the user's name for the same spot
    A.learn_camera(cam_id, 60)
    s3 = c.get(f"/api/analysis/cameras/{cam_id}").json()
    assert any(e["name"] == "Pick housing from bin A" for e in s3["model"]["elements"])


if __name__ == "__main__":
    test_analysis_api()
    print("OK")
