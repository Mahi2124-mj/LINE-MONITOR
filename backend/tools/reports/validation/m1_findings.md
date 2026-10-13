# M/C 1 "Upper Rail Greasing m/c" (camera 1) – video-verified cycle breakup

Data: recordings/cam_1, 2026-10-09 23:30–23:50 (A) and 2026-10-10 00:00–00:20 (B); 640x360 at ~2.85 fps (one frame ≈ 0.35 s).
16 consecutive cycles reviewed frame by frame (23:34:55.71 → 23:38:25.08); the rest processed by the rules with spot checks.

## Scene
- Camera from above-left (label YHB_SS_UPR_RAIL). One operator (blue uniform, cap, glasses, dark gloves), box centre-x 0.54–0.69. Background workers sometimes top centre/right.
- Machine on the left (x ≈ 0.30–0.50): two dark-red columns, yellow bar, fixture/nest ≈ x 0.38–0.50, y 0.55–0.70.
  Small red carriage rests at (0.345–0.375, 0.48–0.52); once per cycle it moves into (0.355–0.395, 0.52–0.565) for ~1–1.4 s = machine stroke (only clearly visible machine motion).
- Input crate (blue) behind the fixture at (0.45–0.58, 0.25–0.45) with dark rails in U dividers; operator reaches in with the right arm; it empties visibly.
- Front-bottom crate (0.50–0.67, 0.70–1.0): white items until 23:42:30, dark rails afterwards; not touched in normal cycles.
- Transparent box with yellow/black tape on the right (0.68–0.92, 0.45–0.98); hands go to its left side/edge every cycle; whether a rail goes in can't be resolved.

## Elements (median duration)
1. walk_to_fixture 1.39 s
2. fixture_work_1 2.42 s – both hands low at the fixture (interpretation: remove greased rail; part not visible)
3. reach_into_crate 0.70 s – right arm into blue input crate
4. load_fixture 1.05 s
5. two_hand_handling 1.74 s – both hands together at yellow-bar height (content not visible)
6. turn_carry_to_box 1.03 s
7. at_box 4.06 s – machine stroke happens during this element
- crate_change (cycle 14) 2.09 s

Cycle (walk start → next walk start): median 13.05 s (12.15–14.28). Stroke-to-stroke: A 13.21 s, B 13.63 s.
at_box absorbs fixture-phase variation (r = −0.80): pace set by something outside the frame.

## Detection rules (detect2.py) and error vs visual (16 cycles)
- Pre-filter: use r["op"]; drop frames with box top < 0.05 or centre-x outside [0.45, 0.80]; forward-fill centre-x.
- machine stroke: red pixels (H<8 or >170, S>120, V>120) in x 0.355–0.395, y 0.520–0.565 > 0.03; merge runs < 1 s apart – 16/16.
- turn_carry_to_box: FIX side centre-x < 0.585, BOX side > 0.625; last FIX→BOX before a stroke – ≤ 0.01 s.
- at_box: first frame after turn with (L wrist x≥0.66 & y≥0.57) or (R wrist x≥0.60 & y≥0.58) – median 0.01, max 0.70 s.
- walk_to_fixture (cycle start): first BOX→FIX after the stroke, traced back to box left edge x0 dropping ≥0.01 below its max at the box – ≤ 0.35 s.
- fixture_work_1: R wrist x ≤ 0.56 & y ≥ 0.53 – ≤ 0.01 s.
- reach_into_crate: R wrist x < 0.52 & y < 0.48 – 15/16 exact, 1 miss +2.4 s (back turned).
- load_fixture: R wrist y ≥ 0.52 after reach – median 0.17, max 0.70 s.
- two_hand_handling: ≥2 frames after load, both wrists y ≤ 0.63 & R wrist x < 0.57 – median 0.34, max 0.69 s.
- crate change (low confidence): dark fraction (V<70) in x 0.47–0.57, y 0.31–0.45 jumps ≥ +0.05 at a stroke.
- operator absent: op null or nobody with centre-x in [0.45, 0.80].
Errors are optimistic (review strips centred on the rule proposals). Window A automatic medians 1.40/2.43/0.70/1.05/1.73/0.70/3.83 s, cycle 13.22 s.

## Not reliably detectable
Fixture→crate boundary with back turned; load vs two-hand split (±0.7 s); whether a rail is removed/loaded/placed; machine cycle end; crate changes from the region.

## Open questions for the user
1. What happens in fixture_work_1 (remove greased rail, unclamp)?
2. What is the two-hand handling (inspection, wiping, two-hand start buttons)?
3. Where does the rail go at the transparent box (chute to station 2 / bin), every cycle?
4. What starts the stroke (light curtain, auto, button)?
5. Why does he wait at the box (~4.1 s)?
6. Full machine cycle time? 7. Rails per crate / crate-change standard / front-bottom crate content? 8. Causes of stops 23:41:03–23:44:15, 00:12:05–00:13:54.

## Abnormal cycles / stops
C4, C9: extra 2–3 s at fixture looking back-right; C13: slow pick from nearly empty crate; C14: crate change.
Stops (no stroke): 23:41:03–23:44:15 (operator present, front crate swap 23:42:40), 00:00:51–00:01:53 (operator out of view 00:01:02–23), 00:04:02–00:04:25 (crate change), 00:04:38–00:05:22, 00:12:05–00:13:54, 00:19:04–00:19:21 (crate change).

Files here: annotations.json, annotations_detail.json, example_cycle.jpg, detect2.py, evaluate.py (eval_result.json), feat.py, redfeat.py, cratefill.py, stats.py, make_outputs.py, evidence sheets.
