# Step 5 "Semi Automatic & Bending m/c" (camera 5) – video-verified cycle breakup

Data: recordings/cam_5, 2026-10-09 23:30–23:50 (main) and 2026-10-10 00:00–00:20 (hold-out); ~2.85 fps (0.35 s / frame).
"+x s" = seconds after machine start (transfer).

## Scene
- Fisheye-like, tilted ~30°, left ~20% black; overlay YHB_SS_SEMIAUTO.
- Fr-labelled press on the left; guard tube top-left (0.25–0.43, 0–0.25): press head drops into it once per cycle.
- Centre ram (0.55–0.70, 0.30–0.55) comes down on a nest once per cycle.
- Transfer "ladder" (0.55–0.80, 0.30–0.60): first thing that moves at machine start.
- Carriage/slide (0.78–1.0, 0.50–0.95): short stroke, later a long stroke towards the camera (white plate visible).
- Load nest bottom-right (0.80–1.0, 0.70–1.0): operator's blue-sleeved hand visible 1–3 frames per cycle; afterwards a dark part lies in the nest.
- Operator body NOT in frame. A blue person often partly visible at the top edge (0.36–0.58, 0–0.15) – identity unknown.
- Where finished parts leave: not visible.

## Elements (median of 15 cycles c10–c24, 23:36:05–23:39:26)
| Element | Starts | Duration |
|---|---|---|
| load_part (hand in nest) | −2.08 s | 1.04 s |
| wait_for_machine_start | −1.04 s | 1.04 s |
| transfer (= machine start) | 0 | 1.39 s |
| carriage_short_stroke | +1.39 s | 0.35 s |
| fr_press_down | +1.73 s | 2.44 s |
| ram_down (fully down) | +4.18 s | held 1.74 s |
| carriage_forward | +5.23 s | 2.77 s |
| ram_up | +5.92 s | – |
| carriage_back | +7.98 s | 0.35 s |
| machine_rest (waiting for operator) | +8.33 s | median 2.1 s (up to 30 s) |

Machine motion start→rest 8.33 s (7.95–8.42). Load→next load 12.54 s (11.1–19.8). Start→start: 23:34–23:50 13.05 s (67 cycles), 00:00–00:20 14.25 s (76 cycles).
All long cycles come from the rest wait (operator); machine part and load→start never stretch.

## Abnormal
- 23:30:00–23:33:30 no strokes, second person behind guard (start-up, excluded).
- Waits > 6 s: 23:38:58 7.7, 23:39:16 9.4, 23:39:50 9.5, 23:40:36 30.4, 23:41:17 7.6, 23:43:49 9.1, 23:45:17 6.7, 23:46:12 6.6, 23:48:19 7.0 s; hold-out: 27.1 (00:05:15), 27.8 (00:09:55), 20.8, 15.8, 13.9 s.
- No rework / double strokes.

## Detection (detect2.py; frames 160x90 grey; X_tpl = mean abs diff to template frames template_*.png:
idle 23:35:13.43, Fr down 23:35:17.24, ram down 23:35:32.51, carriage fwd 23:35:20.69; corner_mot = frame-to-frame diff)
Regions: tube 0.25,0.00,0.43,0.25 · nest 0.55,0.30,0.70,0.55 · ladder 0.55,0.30,0.80,0.60 · carriage 0.78,0.50,1.00,0.95 · corner 0.80,0.70,1.00,1.00 · cornerblue 0.875,0.80,1.0,1.0 (H95–130,S>60,V>40)
1. Fr at bottom: tube_dwell < 30 ≥2 frames; back up when tube_idle ≤ 17.
2. transfer: walk back from Fr while nest_idle > 7 or ladder_idle > 7 or right_idle > 8 (≤ 2.7 s); else Fr − 1.73 s.
3. short stroke: first frame in [transfer, Fr] with right_fwd < 20.
4. ram_down: first frame after Fr run with nest_tool < 12; ram_up: next with ≥ 12.
5. carriage_forward: from ram_down, right_fwd < 20; back: next ≥ 20; rest: right_idle < 8 and ladder_idle < 8.
6. load_part: first frame in [max(transfer−3.3, rest+0.3), transfer−0.9] with corner_mot onset > 6 or cornerblue > 0.07.
7. Cycle = load → next load (fallback transfer − 2.08 s).

Accuracy in-sample (tuned on c10–c24, blind manual reading): load 15/15, transfer 14/14, short stroke 13/14, Fr 13/14, ram down 15/15, ram up 15/15, carriage back 14/15 (misses = 1 frame).
Hold-out 00:03:16–00:04:30 (6 cycles): load 6/6, transfer 6/6, Fr 3/6 exact (3 × 1 frame late), ram 6/6, carriage back 6/6.
Coverage: 65/67 and 73/76 cycles with all elements.
Limits: ±0.35 s per boundary; 0.6–1.0 s recording gaps at 60 s rotations; start trigger and off-screen operator work invisible; templates must be re-captured if camera/lighting changes. Pose data unusable (false detections on the moving press).

## Open questions for the user
1. Who is the blue person at the top edge? Where does the Step-5 operator stand?
2. How is the machine started (two-hand button, foot switch, sensor)?
3. What do Fr press, ram and carriage strokes do? Where does the finished rail leave and who unloads it?
4. Cycle load→load (operator view) or start→start (more robust)?
5. Was 23:30–23:33:30 a planned stop/changeover?
6. Can the camera be re-aimed to see the operator, or fps raised (≥ 5)?

Files: annotations.json, manual_c10_c24.json, det2_2330.json, det2_0000.json, example_cycle.jpg, feats.py, addfeat.py, addfeat2.py, detect2.py, evalman.py, build_ann.py, template_*.png, evidence sheets.
