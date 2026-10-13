# Breakup reports (developer tools)

Build a report of one machine from its recording (`backend/data/recordings/cam_<id>`), shown on the dashboard's **Reports** page
(`reports/<name>/` in the project folder: `index.html`, `video.webm`, `frames/`, `timeline.json`, `cycles.json`, `data.json`, `meta.json`).

All report text is plain English; the final station's container is called a **bin** (not a crate).
Every report with elements has a **variation (baratsuki) chart** (`backend/app/static/report_charts.js`, data in `cycles.json`):
the actual element times of consecutive cycles side by side (stacked per cycle, one strip per element with median and
10-90 % band, statistics table with min / median / max / range / CV).

```bat
cd backend\tools\reports
..\..\.venv\Scripts\python breakup.py 09:20:00 09:26:30 "..\..\..\reports\rail-assy-01_0920"
..\..\.venv\Scripts\python make_report.py "..\..\..\reports\rail-assy-01_0920"
```

`breakup.py` is written for camera 3 (Rail Assy #01, one operator running #01 and #02): operator position classes
(machine #01, machine #02, walking, away) use that camera's floor coordinates. The reference-cycle steps in `make_report.py`
were written by watching the video frame by frame. Adapt both for another machine; add a `meta.json` (title, date, window,
cycles, median_cycle, highlights) so the Reports page can list it.

## Final station: inspection + bin timing

Made **automatically** by the report engine every 2 hours (`final_report.py --auto`: last hour of statistics, latest
5.5 minutes as video, folder `reports\auto_final_<date>_<time>\`) and with *Generate now* on machine 6. By hand:

```bat
..\..\.venv\Scripts\python final_report.py 18:40:00 19:50:00 19:29:00 19:34:30 2026-10-09
```
(statistics from / to, video from / to, date). Camera 6 = inspection operator (left person), camera 7 = bin from above.
Every bend of the operator to the bin is classified: rail put in the tray, mesh + new empty tray (camera-7 fill drops),
separators (after a new tray until the first rail), bin change (camera 7: bin out of view); the time between
bends is split at the machine bed (camera 6): in-hand check before the machine -> in the machine (load + check) ->
in-hand check after taking the rail out; then putting it in the bin.

## Stations 1-5: element breakup (`station_breakup.py`)

One detector per station, each built after watching the station's video frame by frame (2026-10-09 23:30-23:50,
2026-10-10 00:00-00:20). Findings, regions and measured accuracy: `validation/<station>_findings.md`; the frame-by-frame
annotations: `validation/<station>_annotations.json`.

| key | station | cameras |
|---|---|---|
| m1 | Upper Rail Greasing | 1 |
| m2 | Lower Rail Grease & Bar Coding (operator A; B summarised) | 2 |
| m34 | Rail Assy #01 + #02 (one operator, both machines) | 3 + 4 |
| m5 | Semi Automatic & Bending (hand + machine elements) | 5 (templates in `templates/m5_*.png`) |

```bat
..\..\.venv\Scripts\python station_breakup.py m1 --auto
..\..\.venv\Scripts\python station_breakup.py m34 23:30:00 23:59:59 23:43:10 23:48:40 2026-10-09
..\..\.venv\Scripts\python station_breakup.py m2 --validate      :: detector vs the annotations (needs the recording, kept 12 h)
```
The report engine runs `--auto` for every station every 2 hours (folders `reports\auto_<key>_<date>_<time>\`).
