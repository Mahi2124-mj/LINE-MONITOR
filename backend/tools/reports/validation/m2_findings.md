# Step 2 "Lower Rail Grease & Bar Coding m/c" (camera 2) – video-verified breakup

Recording cam_2, 640x360, ~2.83 fps (±0.35 s). 18 consecutive cycles hand-annotated (2026-10-09 23:35:59–23:40:17).

## Scene (normalised x, y)
- Rack/trolley with blue bins, left edge x < 0.15: A takes a dark rail from the bins.
- Left machine: cabinet + HMI (0.15–0.30, 0–0.5); nest with yellow bars (0.30–0.46, 0.38–0.56); dark moving part (0.30–0.37, 0.34–0.42) makes 2 strokes per cycle while A is at the rack.
- Orange/black device at ~(0.24, 0.61): A holds the incoming rail at/past it ~0.3–0.7 s (function not visible).
- Dark sloping panel between machines (0.40–0.48, 0.55–0.70): A lays the checked rail here; where it goes is not visible.
- Right machine: white V-holder (0.488–0.535, 0.435–0.50) holds one rail; transfer gripper above it (0.50–0.60, 0.25–0.40), one stroke per cycle, refills the holder; green lamp (0.503–0.522, 0.603–0.628) lit ~2.5 s per stroke; fixture (0.62–0.76, 0.35–0.58) where B puts a rail.
- Right edge x > 0.8 = B's area; B leaves the frame to the right every cycle.
- People: A = plain blue cap, beard; B = blue cap with light-blue panel, glasses; third person sometimes passes bottom-left. Split: A = centre x < 0.6 and box top < 0.5; B = centre x ≥ 0.6. Server `op` flips A 45% / B 31% / none 24%.
- No production 23:30:00–23:34:23.

## Operator A (cycle starts when the holder is seen empty after A's pick)
| # | Element | Median (18 / 15 normal) | Range |
|---|---|---|---|
| A1 | Carry to rack | 2.4 / 2.4 s | 2.1–5.9 |
| A2 | At rack (hands in bins) | 4.8 / 4.5 s | 3.8–20.2 |
| A3 | Walk back (rail in hand) | 2.1 / 2.1 s | 1.0–2.8 |
| A4 | Nest exchange | 1.0 / 1.4 s | 0.7–1.4 |
| A5 | In-hand check | 0.7 / 0.7 s | 0.3–1.7 (upright check in 9/18 cycles) |
| A6 | Place in chute | 0.7 / 0.7 s | 0.3–0.7 |
| A7 | Pick from holder | 0.7 / 0.7 s | 0.3–1.0 |
| | Cycle | 12.4 / 12.2 s | 11.5–30.9 |
Full windows: median 13.6 s (10-09), 13.9 s (10-10).
Left-machine strokes: +1.4–2.4 s and +5.6–7.3 s after pick; stroke 2 ends 0.3–2.1 s before A's hands are back in the nest (A never waited).

## Operator B (loop ~13.3 s)
~9 s away at the right edge (activity not visible), ~4.5 s at the machine: hands in the fixture ~1 s while the gripper moves, the lamp is lit and the holder is refilled. B's wrist in fixture median +0.7 s after transfer start; B arrives median 1.8 s before the transfer.
Coupling: each A pick is followed by exactly one transfer (67/67 on 10-09, 77/78 on 10-10). Holder empty → transfer median 1.8 s (10-09), 3.5 s (10-10). On 10-10 00:01:24–38 A worked at B's machine.

## Abnormal
Cycles 15–17: rack 9.7, 20.2, 10.9 s + 1.5–4 s standing at the machine after the pick (cycle 16 = 30.9 s). Auto: 23:40:44 29 s; on 10-10 9 cycles > 20 s.

## Detection rules (m2rules.py), error vs 18 annotated cycles
- Start/end (holder empty): HOLD region (0.488,0.435,0.535,0.50) fraction of grey > 165; rail ≈ 0.27–0.33, empty > 0.36, hand < 0.22; event H[i]>0.36 & H[i+1]>0.36 & H[i-1]≤0.36 & min(H[i-3..i-1])<0.30, ≥5 s since last – 18/18 same frame.
- Rack arrive: A centre x < 0.08 – MAE 0.18 s (16/18 within 0.4).
- Rack leave: start of final run with A's left shoulder conf ≥ 0.85 and x ≥ 0.03, ≥1 s after arrival – MAE 0.28 s.
- Nest in: first wrist (conf ≥ 0.3) in (0.29,0.38,0.46,0.56) – MAE 0.14 s. Nest out: end of nest run + 1 frame – MAE 0.16 s.
- Place in chute: wrist x > 0.42 or in chute (0.40,0.55,0.48,0.70) or holder area (0.455,0.40,0.56,0.555) – MAE 0.16 s.
- Reach holder: HOLD fraction < 0.22 – MAE 0.16 s.
- Transfer: gripper region motion fraction > 0.2 while lamp green excess > 12.
- B at machine: box x0 < 0.76; B wrist in fixture (0.60,0.33,0.80,0.62).
- Left-machine stroke: WEDGE (0.30,0.34,0.37,0.42) mean grey < 72 (idle 79–83) while A centre x < 0.17.
Not reliable: place/pick individually (±0.35 s; together more robust), quality of A's check, A's work at the rack, orange device use, where rails go, B's work out of frame, right machine process time.

## Open questions for the user
1. Which machine greases and which does the bar code? 2. Where does the rail placed on the dark panel go? 3. Where does A put the rail from the holder? 4. What are the rack bins for? 5. Is the orange/black device a scanner? 6. Where do B's rails come from? 7. Does B start the transfer? 8. Is the upright check mandatory (skipped 9/18)?

Files: annotations.json, example_cycle.jpg, example_regions_B.jpg, m2rules.py, evalrules.py, runall.py, bstats.py, annotations_src.py, sigA.npy, sigA_p.jsonl, sigB.npy, sigB_p.jsonl.
