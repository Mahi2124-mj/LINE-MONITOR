# Line Monitoring – camera based assembly-line analytics

Watches every process step (station) of every production line with one or more cameras and answers:

| Question | Where |
|---|---|
| Kis step me kya part add hota hai, aur next step kya hai? | Line page → **Process flow** (Step 1 → Step 2 → …, "Part added" chips) |
| Har step ka cycle time kitna hai? Live timer? | Line page cards, Station page trend / histogram / stats |
| Kaunsa step sabse zyada time le raha hai (bottleneck)? | Overview, Line page (red badge), **Yamazumi / line balance** chart vs takt |
| Operator ki extra movement kya hai jo kam ho sakti hai? | Station page → **Movement analysis**, heatmap, spaghetti diagram; **Movement & waste** page |
| Kya improve karein? | Auto-generated **recommendations** (line balancing, long reaches, walking, extra picks, waiting, unstable cycles) |
| Problem abhi ho rahi hai? | **Alerts**: camera offline, stoppage, slow cycle, over-takt, unbalanced line, excess motion |

Many lines × 5–6 cameras per line are supported; each camera runs in its own worker thread.

---

## Start / Stop (no terminal needed)

| | |
|---|---|
| **Start** | double-click **Line Monitor** on the Desktop (or `Start Line Monitor.bat` / `Line Monitor` shortcut in this folder). The server starts in the background (no window) and the dashboard opens at **http://localhost:6010** |
| **Stop** | double-click `Stop Line Monitor.bat` |

* Everything (dashboard, API, live video) runs on **one port, 6010**. Port 6002 is used by another project on this PC and is not touched.
* **From other PCs / phones on the LAN**: **http://192.168.30.81:6010** (factory Ethernet) or **http://192.168.100.32:6010**
  (office Wi-Fi, DHCP – the address can change). There is no login: everybody on these networks can open and change it.
  To allow only this PC again: `set LM_HOST=127.0.0.1` before starting.
* **Remote access over Tailscale** (only devices in your tailnet): **http://100.98.111.45:6010** or
  **http://tbdi-bi-svr-01:6010** (or `http://tbdi-bi-svr-01.tailb7c0d7.ts.net:6010`). This is Tailscale's own TCP forwarder
  (`tailscale serve --bg --tcp=6010 tcp://127.0.0.1:6010`), it survives reboots; switch it off with `tailscale serve --tcp=6010 off`.
  There is no login in the dashboard – everybody in the tailnet can open it.
* First start on a new PC runs `setup.bat` automatically (Python venv + packages + frontend build, needs Python 3.10–3.12 and Node.js).
* Clicking Start again while it is running just opens the dashboard.

For developers only:

```bat
dev\start-dev.bat    :: backend :6010 + Vite hot reload on :6012 (developers only)
cd frontend && npm run build    :: after changing the UI (the backend serves frontend\dist)
backend\.venv\Scripts\python backend\tests\test_pipeline_sim.py    :: vision accuracy tests (also test_video_motion.py)
```

### Add a line (the normal way)
Sidebar → **Lines & cameras** → *New line*:
1. Line name (takt time optional, default 60 s)
2. Camera login (username / password) – used when you type only an IP
3. One row per process step: **step name** + **camera IP** (e.g. `192.168.1.64`) or a full `rtsp://` / `http://` URL
4. **Check** each camera (or *Check all*): the app finds the stream (tries Hikvision, Dahua/CP Plus, TP-Link and other common
   RTSP paths) and shows a live photo. Wrong IP / password gives a clear message.
5. **Save & go live** – the cameras start and the line page opens.

Parts added per step, target times and detection zones can be refined later under *Advanced* (link at the bottom of the lines list)
and on each camera's page.

### Cycle analysis – element breakup of every cycle (sidebar → *Cycle analysis*)
1. Open a station and click **Start recording** (6 fps). Video + the operator's hand positions are recorded
   (`backend\data\recordings`, kept 12 h).
2. After ~10 minutes of normal work the **elements are learned automatically** – no process definition needed: places where the
   operator's hands work (e.g. "left hand at bin, right hand at fixture") become elements; the element that occurs once per cycle
   with the most regular rhythm marks the cycle start. Rename the elements (pencil), change the cycle start if needed.
3. Every cycle is split into elements with start / duration, compared with the **standard** (most common sequence, median times)
   or with a **master cycle** you choose ("Set as master"), and the issues are listed: element slower than standard, element not
   done, repeated / unplanned action, done out of order, operator away, hand outside the normal work area, cycle over standard.
4. Click a cycle → its video plays with the element timeline under it (click an element to jump to it).

Limits: it sees *where* the hands work and *how long*, not the quality of the work (grease amount, torque, part orientation –
that needs a trained object model or machine signals). Hands hidden behind the machine reduce accuracy.

### Reports – video breakup of every machine (sidebar → *Reports*)
**Made automatically** for every recorded machine every 2 hours while the line runs (and on *Generate now*): about 5 minutes
of the machine's video (the latest back-to-back cycles) with an overlay, where each cycle starts / ends (same cycles as the
dashboard), every cycle split into segments – the places where the operator works (found automatically, the one at the part
fixture is named after it), walking between them, operator away / not visible – abnormal cycles with the reason, a typical cycle
with a frame per segment, and observations (walking share, hands at the fixture, variation, target). Where no operator is
visible (automatic machine) the segments are machine moving / still. The newest 12 automatic reports per machine are kept
(`reports\auto_cam<id>_<date>_<time>\`); each report is made by a separate low-priority process (`app\services\report_gen.py`,
log `backend\data\report_gen.log`), so the cameras are not slowed down. Opens inside the dashboard, also over LAN / Tailscale.
Stations 1–5 get an automatic **element breakup** (each built after watching that station's video frame by frame: every
step of the operator / machine with its time, every cycle) and the final station an automatic **inspection + bin timing** report (cameras 6 + 7: inspection time per rail,
putting rails in the bin, mesh + new tray, separators, bin change). Every report has a **variation (baratsuki) chart**: the
element times of consecutive cycles side by side, per element with min / median / max / range. A hand-checked detailed report (step-by-step
from the video) can sit next to them: `backend\tools\reports\README.md`.

### Cameras – everyday controls
* **Video on/off** (top bar): stops all live video in the browser (cameras keep analysing). Remembered per browser.
* **Disable / Enable** a camera: on the Cameras page tiles or the camera page – a disabled camera is not connected or analysed.
* **Zone editor** has its own page (`Zones` button / `/cameras/<id>/zones`). A step can have **several part fixtures**:
  draw one *part zone* per fixture – a unit leaving any fixture counts as one finished cycle of that step.
* IP cameras are analysed from their **low-resolution sub stream** automatically (Hikvision / Dahua / CP Plus and similar);
  the main stream is used if no sub stream exists. 7 cameras ≈ 4–5 CPU cores at 4 fps each – lower *Process FPS* to 3 to save CPU.
* The server runs in the background without a window; logs: `backend\data\server.log`.

### Demo mode (off by default)
Only with `set LM_DEMO=1` and an empty database, the backend creates **3 demo lines (6 + 5 + 4 steps)** with a **simulated camera per step** and 3 days of history.
The simulated cameras render a top-down workbench with an operator, part bins, a far rack and conveyors; stations of a line are coupled through buffers
(the bottleneck starves downstream steps). Their frames go through the **real** detection pipeline, so the demo exercises exactly the code real cameras use.

To start clean with your own lines: Setup page → *Danger zone → Clear data* (removes cycles/alerts/heatmaps), delete the demo lines,
or stop the server and delete `backend\data\` and start with `LM_DEMO=0`.

---

## How it works

```
camera (RTSP / USB / file / simulated)
  └─ CameraWorker thread (one per camera, auto-reconnect)
       ├─ tracker: YOLO-pose (wrists, shoulders) | motion blobs (fallback) | simulated ground truth
       ├─ analyzers (plugins, in order)
       │    cycle_time  → part-zone presence vs. empty reference image  → cycle start / end per station
       │    movement    → hand travel, reaches outside work area, picks in bin zones, walking, idle
       │                  → splits each cycle into work (value added) / motion waste / waiting
       │    heatmap     → where the hands spend time (per camera per day)
       ├─ cycle saved to SQLite → live registry → websocket → UI
       └─ MJPEG stream with overlay (zones, skeleton, state, live timer)
FastAPI: REST + /ws/live + analytics + rule-based recommendations + alert engine
React (Vite, TypeScript, Tailwind, Recharts): dashboards, zone editor, setup
```

### Key definitions
* **Cycle time** – time between two consecutive part departures at a station (includes waiting).
* **Operator content** = work + motion waste. Bottleneck and line balance use content, because in a coupled line every station's
  cycle time becomes equal to the bottleneck pace.
* **Takt time** – demand pace of the line (target output/hr = 3600 / takt).
* **Line balance efficiency** = Σ content / (number of steps × max content).
* **Motion waste** – time a hand is outside the normal work area (long reach), the operator walks, or the operator is away while a part waits.
* **Waiting** – no part at the station (starved/blocked) or hands idle.
* **Est. saving** – ≈ 80 % of the motion waste + 1 s per extra pick (what is realistically removable).

---

## Adding a real camera

1. **Setup** → select the line → add stations (name, operation, parts added, target cycle, expected picks per cycle).
2. **Cameras** → add camera: source type `rtsp` (e.g. `rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101` for Hikvision,
   `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` for Dahua/CP Plus), `usb` (index `0`, `1`…), `http` (MJPEG URL) or `file`
   (a recorded video path – plays in real time, useful for testing).
3. Open the camera → **zone editor**, draw on the snapshot:
   * `part_zone` – the fixture where the unit sits during the step (**required for cycle detection**)
   * `work_area` – the normal working area / reach zone of the operator (hand outside = long reach)
   * `pick_zone` – each parts bin / tool position (counts picks)
   * `trigger_zone` – optional alternative cycle signal (hand enters, e.g. "place finished part" or a push button)
   * `exclusion` – areas to ignore (passing people, another station)
   Each zone can be assigned to a station → **one overview camera can cover two stations**, or **several cameras can watch one station**
   (put the cycle zone on only one of them).
4. With the fixture **empty**, click **Capture empty reference**. Part presence is detected by comparing the part zone with this image.
5. Tune if needed: `presence_threshold` (fraction of zone pixels that must change, default 0.15), debounce, min/max cycle.

Camera placement: mount above / slightly in front of the station, the whole fixture + bins + operator's hands in view, fixed (no PTZ),
stable lighting. 720p is enough – frames are processed at 640 px width.

**Cycle methods**: `part_presence` (recommended), `trigger_zone` (hand enters zone = cycle boundary), `activity` (motion in zone – least accurate).

### Performance
* Simulated cameras: ~0.3 CPU core for all 15.
* YOLO pose on CPU: ~40–80 ms per frame → ~4–6 real cameras at 3–5 fps. For many cameras use an NVIDIA GPU:
  install CUDA torch, then `set LM_POSE_DEVICE=cuda:0`. Lower `process_fps` per camera (3–4 fps is enough for cycle times ≥ 10 s).

### Configuration (environment variables)
| Variable | Default | |
|---|---|---|
| `LM_PORT` / `LM_HOST` | 6010 / 127.0.0.1 | `LM_HOST=0.0.0.0` only if other PCs should open the dashboard |
| `LM_DEMO` | 1 | seed demo lines when the DB is empty |
| `LM_DATA_DIR` | backend/data | SQLite DB + reference images |
| `LM_POSE_MODEL` | backend/models/yolo11n-pose.pt | any ultralytics pose model |
| `LM_POSE_DEVICE` | cpu | `cuda:0` for GPU |
| `LM_PROCESS_WIDTH` | 640 | analysis resolution |

---

## Extending (future options)

New capabilities are **analyzer plugins** – `backend/app/vision/analyzers.py`:

```python
@register
class PpeAnalyzer(Analyzer):
    key = "ppe_check"; name = "PPE compliance"; order = 40
    description = "Gloves / cap detection"
    def process(self, fc):             # every frame: fc.frame, fc.persons, fc.station_person, fc.part_present
        ...
    def contribute(self, draft):       # add data to the cycle being saved
        ...
    def draw(self, img, fc):           # overlay on the live stream
        ...
```

Enable it per camera in the camera config (`analyzers` list) – the UI toggles come from `GET /api/analyzers`.
Already listed as *coming soon*: part verification (object detection that the right part was added at each step), PPE, ergonomics (RULA/REBA from
pose), operator identification, visual defect detection. Recommendation rules live in `backend/app/services/recommendations.py`,
alert rules in `backend/app/services/alerts.py`.

Other natural next steps: shift calendar & OEE, PLC/MES integration (unit serial per cycle), user login/roles, PostgreSQL for very large plants.

---

## Project layout

```
backend/
  run.py                    start server
  app/main.py               FastAPI app, startup, serves frontend/dist
  app/models.py, schemas.py DB tables / API schemas (mirror of frontend/src/api/types.ts)
  app/routers/              lines, stations, cameras (+MJPEG, zones, reference), dashboard (overview, movement, alerts, export, ws)
  app/services/             analytics, recommendations, alerts, seed (demo), cycles, heatmaps
  app/vision/               worker, manager, sources, trackers, analyzers, synthetic camera, geometry
  tests/test_pipeline_sim.py  runs the real pipeline on the simulator and checks detected cycles against ground truth
frontend/                   React + TypeScript + Vite + Tailwind + Recharts
```

API docs (Swagger): http://localhost:6010/docs
