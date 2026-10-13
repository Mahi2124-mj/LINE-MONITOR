# Rail Assy m/c #01 + #02 (steps 3+4, cameras 3+4) - video-verified work-cycle breakup

Data: recordings 2026-10-09 23:43:18-23:49:48 (14 consecutive loops, annotated frame by frame on both cameras),
23:34-23:40 (4 held-out loops + one irregular period); the detector was also run on 2026-10-10 00:00-00:10 (not verified).
Camera 3 ~4.2 fps, camera 4 ~2.8 fps, 640x360, so every boundary has a time resolution of about +-0.15 s (cam3) / +-0.2 s (cam4).
Clock sync: operator A is seen at the same moment in the right part of cam3 and the bottom-left of cam4
(e.g. 23:45:31.7-23:45:32.3); no offset is visible at frame resolution.
Everything below was checked on frames. "Not visible" means it could not be seen at this resolution.

## 1. Scene (what is seen)

**Camera 3 (#01 camera)**: view from above the front of m/c #01.
- #01 machine on the left; its fixture/mechanism is upper-left (x 0.0-0.30, y 0.35-0.70).
- Green bin of small green parts at the operator's bottom-left (x 0.30-0.45, y 0.70-0.85; the bin reaches the image bottom).
- Small blue tray + blue clamp next to the fixture (x 0.33-0.47, y 0.42-0.62).
- Rail rack: horizontal black/steel rails lying at the bottom centre (x 0.40-0.66, y 0.80-1.0).
- Right part (x > 0.6) = walkway towards #02. A second operator **B (black trousers)** stands/works at the right edge (x 0.75-1.0).
- Machine #02 is partly visible in the upper middle of cam3 (x 0.48-0.72, y 0.05-0.55).

**Camera 4 (#02 camera)**: view from above #02, from the walkway side.
- #02 fixture/mechanism upper-right (x 0.60-1.0, y 0.0-0.32); control panel with a red button at the top-right edge.
- Green tray of small parts in front of the machine (x 0.50-0.64, y 0.40-0.58).
- Front-right corner where the finished rail is taken out (x 0.60-0.76, y 0.56-0.72).
- **Vertical rail stand** at the bottom centre/left (x 0.25-0.50, y 0.66-1.0). A puts the finished #02 rail into it (rails stand vertically).
- Yellow vertical bars on both machines (they look like light curtains; not verified).
- The bottom-left / left edge of cam4 is the right edge of cam3 (where B stands).

**People**
- **A (blue trousers, blue shirt, cap)** is the operator of #01 and #02. In all 18 checked loops only A works the two machines.
- **B (black trousers)** stands between the cameras (cam3 right edge / cam4 bottom-left). Seen: placing a rail on top of the #01 rack
  (23:45:29.2-30.5; the rack holds 4 rails at 30.6), reaching to the rack (23:37:41-42, 23:39:14-16), arm at the vertical stand (23:45:32.7-33.0).
- A third person in blue (blue trousers) sometimes appears at the left of cam4 (e.g. 23:36:07.3-08.4, 23:39:00-07). Identity and job unknown.

**Material flow seen (per loop)**: a rail is taken from the cam3 rack and put into #01. At the end of the #01 visit a black rail is
pulled out of #01. A picks another rail from the rack and walks to #02 with rail(s). On the way his hand goes down to the vertical stand
(e.g. 23:45:32.4-32.7). One rail goes into #02. At the end of the #02 visit the finished rail is taken out at the front-right and put
vertically into the stand. **Not visible:** how many rails A carries between the machines and what exactly he leaves at the stand on the way.

## 2. Elements of the loop (one operator, two machines)

Loop start = A's first hand contact at #01 (blue clamp/small blue tray or rack). Loop end = the next such contact. One loop gives one rail out of #01 and one rail out of #02 (both seen in every loop).

| # | element (key in annotations.json) | what is seen | median s (min-max, n=14) | share |
|---|---|---|---|---|
| 1 | `01_load_rail` | arrives at #01; in some loops both hands go into the small blue tray first (e.g. 23:45:50.7-51.2); takes a rail from the rack, puts it into the #01 fixture, hands inside the machine | 2.8 (2.2-3.5) | 10 % |
| 2 | `01_parts` | right hand alternates green bin <-> fixture (picking small green parts), ~0.5-0.8 s per pick | 6.1 (4.4-7.5) | 21 % |
| 3 | `01_unload_pick` | pulls a black rail out of the fixture (held vertically), holds/looks at it ~1 s, bends to the rack and lifts the next rail | 3.0 (1.9-7.1) | 12 % |
| 4 | `walk_01_02` | walks right with rail(s) into cam4, hand down at the vertical stand on the way, reaches #02 | 2.0 (1.5-3.1) | 8 % |
| 5 | `02_load_rail` | holds the rail horizontally over the tray and puts it into the #02 upper fixture; the right arm stays in the upper-right of #02 (near the panel). What is touched there is not visible | 2.4 (1.7-6.2) | 9 % |
| 6 | `02_parts` | hand alternates green tray <-> fixture (small green parts) | 5.8 (3.8-10.1) | 23 % |
| 7 | `02_unload_to_stand` | reaches to the front-right corner, takes the finished black rail out (vertical), turns left, walks 2 steps and lowers it into the vertical stand | 2.8 (2.1-3.8) | 10 % |
| 8 | `walk_02_01` | releases the rail, walks back left/up to #01 | 1.8 (0.5-2.4) | 6 % |
|   | **loop** | | **27.6 (21.9-32.6)**, mean 27.8, sd 3.1 | |
|   | #01 visit (1+2+3) / #02 visit (5+6+7) | | 12.0 / 10.8 | |

Compared with the earlier 09:20 finding (~25 s loop: #01 ~11 s, walk 1.3 s, #02 ~12 s, walk 1 s), in this window:
- the loop is longer (27.6 s);
- the #01 visit is 12.0 s;
- the walk #01->#02 is 2.0 s (it includes the stop at the stand);
- the #02 visit, including putting the rail into the stand, is 10.8 s;
- the walk back is 1.8 s.

Small-parts loading takes 6.1 s at #01 and 5.8 s at #02 (earlier: ~5 s / ~7.5 s).

### Machines (frame difference in machine-only regions, measured while A is away)
- #01 (cam3 region x 0.11-0.26, y 0.35-0.70; pixels with |dGray| > 18; threshold 6 %): the mechanism moves while A is at #02.
  Motion stops **14.6 s (13.4-15.1) after A starts pulling the #01 rail out (T2)**. Then there is no motion for a **median of 4.1 s (0.4-11.0)** until A comes back.
- #02 (cam4 regions x 0.55-0.74, y 0-0.18 plus x 0.76-0.86, y 0.26-0.45; threshold 15 %): motion stops **15.1 s (13.7-15.9) after A starts the #02 unload (T6)**.
  Then the machine is still for **3.8 s (0.9-6.1)** until A returns.
- The earliest measurable motion is ~3 s after T2/T6, because A blocks the view before that. So the start of the machine cycle is not visible.
- **Result:** in every annotated loop both machines had stopped moving before A came back. **A never waits for a machine; the machines wait for A**: about 4 s each per loop, plus the time A works at them.

### Abnormal loops / events (with evidence)
- L01 23:43:18: `01_unload_pick` 7.1 s. After the rail-out A stays at the rack with B 23:43:26-23:43:30 and only walks at 43:32.4 (loop 32.5 s).
- L03 23:44:20: `02_parts` 10.1 s. Right arm far into the upper-right of #02 23:44:42.2-43.6, then A turns to the camera with both hands at the front of the tray 23:44:45.0-46.8.
- L05 23:45:20: `02_load_rail` 6.2 s. Right arm held in the upper-right of #02 23:45:35.1-39.3 (4.2 s).
- L11 23:48:02: `02_parts` 9.8 s. A faces the camera with hands at the front of the tray 23:48:23.0-27.2.
- L13 23:48:59: short loop, 21.9 s (#01 visit 9.0 s, walk back 0.5 s).
- **23:38:47-23:39:43 (~56 s): no regular loop.** Sequence:
  - A at #01 23:38:48-38:59, with B next to him.
  - 23:39:02.6-39:10.2: a person in blue (cap) works at the right side of #02 next to the yellow column/panel, hands at the machine side, not in the tray. It is not certain this is A: a third person is also in cam4 at 39:06.7.
  - 23:39:14-39:31: A at #01 (~17 s); B's hand at the rack 39:14.4-15.9.
  - 23:39:32-39:42: A at the #02 tray.
  - Regular loops resume at 23:39:43. Reason not visible.
- A third person in blue is at the cam4 left 23:36:07.3-08.4, while A is still at the #01 rack.

## 3. Per-loop annotation (start time 23:MM:SS.s, duration in brackets)

| loop | T0 #01 load rail | T1 #01 parts | T2 #01 unload+pick | T3 walk->#02 | T4 #02 load rail | T5 #02 parts | T6 #02 unload->stand | T7 walk->#01 | end (=next T0) | loop s | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L01 | 43:18.3 (2.6) | 43:20.9 (4.4) | 43:25.3 (7.1) | 43:32.4 (1.7) | 43:34.1 (3.4) | 43:37.5 (8.1) | 43:45.6 (3.1) | 43:48.7 (2.1) | 43:50.8 | 32.5 | #01 unload 7.1 s: after rail-out A stays at the rack with B (23:43:26-23:43:30) before walking |
| L02 | 43:50.8 (3.4) | 43:54.2 (6.5) | 44:00.7 (3.0) | 44:03.7 (3.1) | 44:06.8 (2.1) | 44:08.9 (5.9) | 44:14.8 (2.8) | 44:17.6 (2.4) | 44:20.0 | 29.2 |  |
| L03 | 44:20.0 (3.3) | 44:23.3 (6.4) | 44:29.7 (2.4) | 44:32.1 (2.5) | 44:34.6 (2.4) | 44:37.0 (10.1) | 44:47.1 (3.2) | 44:50.3 (2.3) | 44:52.6 | 32.6 | #02 parts 10.1 s: arm far into upper-right of #02 23:44:42.2-43.6, then faces camera with hands at tray front 23:44:45.0-46.8 |
| L04 | 44:52.6 (2.5) | 44:55.1 (5.8) | 45:00.9 (3.4) | 45:04.3 (2.3) | 45:06.6 (2.4) | 45:09.0 (5.5) | 45:14.5 (3.2) | 45:17.7 (2.4) | 45:20.1 | 27.5 |  |
| L05 | 45:20.1 (2.6) | 45:22.7 (6.2) | 45:28.9 (3.0) | 45:31.9 (1.5) | 45:33.4 (6.2) | 45:39.6 (6.3) | 45:45.9 (3.8) | 45:49.7 (1.0) | 45:50.7 | 30.6 | #02 load 6.2 s: right arm held in upper-right of #02 23:45:35.1-39.3 |
| L06 | 45:50.7 (3.3) | 45:54.0 (6.2) | 46:00.2 (3.0) | 46:03.2 (1.5) | 46:04.7 (1.9) | 46:06.6 (3.8) | 46:10.4 (2.4) | 46:12.8 (1.2) | 46:14.0 | 23.3 |  |
| L07 | 46:14.0 (3.3) | 46:17.3 (6.4) | 46:23.7 (2.8) | 46:26.5 (3.0) | 46:29.5 (2.5) | 46:32.0 (5.0) | 46:37.0 (2.4) | 46:39.4 (2.4) | 46:41.8 | 27.8 |  |
| L08 | 46:41.8 (3.5) | 46:45.3 (7.5) | 46:52.8 (3.2) | 46:56.0 (1.8) | 46:57.8 (2.1) | 46:59.9 (5.6) | 47:05.5 (3.1) | 47:08.6 (1.5) | 47:10.1 | 28.3 |  |
| L09 | 47:10.1 (2.8) | 47:12.9 (6.1) | 47:19.0 (3.6) | 47:22.6 (1.7) | 47:24.3 (2.1) | 47:26.4 (5.9) | 47:32.3 (2.8) | 47:35.1 (2.0) | 47:37.1 | 27.0 |  |
| L10 | 47:37.1 (2.8) | 47:39.9 (5.5) | 47:45.4 (3.4) | 47:48.8 (1.9) | 47:50.7 (1.7) | 47:52.4 (5.5) | 47:57.9 (2.8) | 48:00.7 (1.3) | 48:02.0 | 24.9 |  |
| L11 | 48:02.0 (2.8) | 48:04.8 (5.4) | 48:10.2 (3.0) | 48:13.2 (2.1) | 48:15.3 (1.8) | 48:17.1 (9.8) | 48:26.9 (3.8) | 48:30.7 (1.6) | 48:32.3 | 30.3 | #02 parts 9.8 s: faces camera, hands at tray front 23:48:23.0-27.2 |
| L12 | 48:32.3 (3.2) | 48:35.5 (5.1) | 48:40.6 (3.4) | 48:44.0 (2.4) | 48:46.4 (2.7) | 48:49.1 (7.0) | 48:56.1 (2.1) | 48:58.2 (1.3) | 48:59.5 | 27.2 |  |
| L13 | 48:59.5 (2.3) | 49:01.8 (4.8) | 49:06.6 (1.9) | 49:08.5 (2.2) | 49:10.7 (2.9) | 49:13.6 (4.8) | 49:18.4 (2.5) | 49:20.9 (0.5) | 49:21.4 | 21.9 | short loop: #01 visit 9.0 s, walk back 0.5 s |
| L14 | 49:21.4 (2.2) | 49:23.6 (6.6) | 49:30.2 (3.1) | 49:33.3 (1.8) | 49:35.1 (2.5) | 49:37.6 (5.6) | 49:43.2 (2.4) | 49:45.6 (2.4) | 49:48.0 | 26.6 |  |

Held-out loops, annotated after the detection rules were fixed (`annotations_heldout.json`, no "end"):
V01 23:34:35.3, V04 23:35:56.2, V06 23:36:47.7, V08 23:37:34.4. Element durations are within the ranges above. In V08 the walk #01->#02 takes 2.8 s, with a stop at the stand 23:37:45.2-45.6.

## 4. Automatic detection (from the recorded pose data only, both cameras)

Code: `detect.py` (+ `track.py`). Input = per-frame persons from the jsonl; `extract.py` adds trouser colour and region motion.

**Operator identity**: A has blue trousers, B black.
- Per person, take the mean BGR of 9x9 px at the hip-knee midpoints. A if B-R > 20; not A if B-R < 8.
- Add continuity: distance to A's last position.
- Add penalties: x0 > 0.74 in cam3 (B's place), and small boxes at the cam4 bottom-left edge.
- The jsonl "op" field is NOT usable: it switches between A and B from frame to frame.

| boundary | rule (normalised coords) | window A (14 loops, rules tuned here) median / p90 / max abs error s | held-out (4 loops) median / max s |
|---|---|---|---|
| loop start T0 `01_load_rail` | cam3: A box x0 < 0.48 and box bottom > 0.80 (2 frames); runs merged over gaps < 2.5 s; a run >= 4 s = one #01 visit | 0.27 / 0.55 / 0.66 | 0.92 / 1.32 |
| T1 `01_parts` | cam3: after the first wrist in FIX3 (0.00,0.40)-(0.30,0.62), the first wrist in BIN3 (0.30,0.70)-(0.45,0.82) | 0.05 / 0.25 / 0.55 | 0.07 / 0.13 |
| T2 `01_unload_pick` | cam3: last frame in the visit with box x0 < 0.29, then the first frame with x0 >= 0.31 (A straightens and steps right with the rail) | 0.10 / 0.27 / 0.39 | 0.14 / 0.33 |
| T3 `walk_01_02` | cam4: A enters bottom-left (box bottom >= 0.845, x0 < 0.35, y0 < 0.2), minus 0.5 s; fallback cam3 x0 >= 0.55 | 0.31 / 0.52 / 0.58 | 0.24 / 0.46 |
| T4 `02_load_rail` | cam4: box x0 >= 0.30, y0 < 0.03, bottom < 0.90 (2 frames) | 0.06 / 0.26 / 0.35 | 0.14 / 0.20 |
| T5 `02_parts` | cam4: right wrist in MACH4 (0.60,0.00)-(1.00,0.32) for 2 frames, then the first wrist in TRAY4 (0.50,0.40)-(0.64,0.58) | 0.05 / 0.38 / 0.43 | 0.18 / 0.28 |
| T6 `02_unload_to_stand` | cam4: first wrist in OUT4 (0.60,0.56)-(0.76,0.72) >= 2 s after T5 (fallback: box x0 < 0.32, minus 0.8 s) | 0.08 / 0.40 / 0.45 | 0.20 / 0.28 |
| T7 `walk_02_01` | cam4: last wrist in STAND4 (0.22,0.66)-(0.50,1.00) before the next #01 visit, minus 0.3 s | 0.41 / 0.78 / 1.30 (1 of 14 missed) | 0.09 / 0.49 |
| end | = next T0 | 0.22 / 0.49 / 0.66 | - |

- **Loop detection**: 14/14 loops found in window A and 4/4 held-out loops found.
- **Irregular period**: 23:38:47-23:39:43 produces **no** loop (the detector jumps from the 23:38:20.8 loop to 23:39:43.2), so it can be used as an "abnormal / no-cycle" flag.
- **Unverified run** on 2026-10-10 00:00-00:10: 19 loops, median 29.0 s (23.3-49.9).
- **Machine-running cue**: frame difference in the machine-only regions above (thresholds 6 % / 15 % of pixels with |dGray| > 18).

**Not reliably detectable / limits**
- What is in the hand (rail vs. small part, number of parts, number of rails carried, what is left at the stand): not resolvable at 640x360 and 3-4 fps.
- Whether a start button is pressed, or what A does with the arm in the upper-right of #02: not visible.
- Loop start T0 when A and B overlap at the right of cam3 (identity swaps): held-out errors up to 1.3 s. The optional small-blue-tray pick at arrival is merged into element 1.
- T7 (rail into the stand): B and the third person also come to the stand area. One loop was missed; max error 1.3 s.
- A third person in blue trousers breaks the trouser-colour identity. Example: at 23:36:07-08 a person in blue trousers stood in the area the T3 cam4-entry rule watches (-0.5 s error in that loop).
- During irregular periods (23:38:47-23:39:43) no element breakdown is possible, only "no regular loop".
- The start of the machine cycle is not visible, because A blocks the view of the machine while he works at it.

## 5. Regions used (normalised x0,y0,x1,y1)
- cam3:
  - FIX3 (0.00,0.40,0.30,0.62): #01 fixture
  - BIN3 (0.30,0.70,0.45,0.82): green bin
  - rack (0.40,0.80,0.66,1.00)
  - blue tray/clamp (0.33,0.42,0.47,0.62)
  - #01 mechanism motion (0.11,0.35,0.26,0.70)
  - B zone: x > 0.74
- cam4:
  - MACH4 (0.60,0.00,1.00,0.32): #02 fixture
  - TRAY4 (0.50,0.40,0.64,0.58): green tray
  - OUT4 (0.60,0.56,0.76,0.72): unload corner
  - STAND4 (0.22,0.66,0.50,1.00): vertical stand
  - #02 mechanism motion (0.55,0.00,0.74,0.18) + (0.76,0.26,0.86,0.45)
- Existing DB zones:
  - cam3 "Part fixture" polygon covers the #01 fixture + blue tray area.
  - cam3 "work" (0.3-0.75, 0.05-0.85) is mostly the walkway/#02 side, not where A works at #01.
  - cam4 "Part fixture" covers MACH4 + tray.

## 6. Open questions for the user
1. Is the rail pulled out of #01 at the end of a visit the one loaded at the start of the same visit, or the one from the previous loop? The #01 mechanism moves only after A leaves, from ~3 s to 14.6 s after the rail-out; which rail it is was not visible.
2. What does A leave at, or take from, the vertical stand on the way #01 -> #02 (hand down at the stand, e.g. 23:45:32.4-32.7)? How many rails does he carry?
3. What does A do with the right arm in the upper-right of #02 (near the panel) after loading the rail (1-4 s each loop)? Start button? Clamping?
4. Is the ~1 s of holding/looking at the rail after the #01 rail-out a required visual check (count it as work) or not?
5. Role of B (black trousers): he puts rails on the #01 rack and reaches at the vertical stand. Which station is he, and should his work count for steps 3/4?
6. What happened 23:38:47-23:39:43 (person working at the right side of #02, no regular loop)? Jam, adjustment or quality check?
7. Who is the third person in blue trousers seen in cam4?

## Files
- `annotations.json`: 14 loops, element -> start unix time + "end".
- `annotations_heldout.json`: 4 loops, no "end".
- `example_cycle.jpg`: loop L05, one key frame per element with the detection regions, plus a timeline of all 14 loops.
- `detect.py`, `track.py`, `extract.py`: detection rules, operator tracking, signal extraction.
- `machrun.py`: machine motion.
- `evalA.txt`, `evalB.txt`: errors per loop.
- `ann_raw.txt`, `ann_raw_B.txt`, `notes.txt`: raw annotations and observation notes.
- `sheets/`: frame sheets used for annotation.
