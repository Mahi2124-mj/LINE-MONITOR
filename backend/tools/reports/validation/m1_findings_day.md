# Station 1 (Upper Rail Greasing, camera 1) – day shift, 2026-10-10

Annotations: `m1_day_annotations.json`, 19 consecutive cycles 09:21:20–09:25:21, frame by frame. The camera-1 recording of
09:19–09:27 is kept in `backend/data/validation_recordings/cam_1`. Check with `python station_breakup.py m1 --validate day`.

## Why the old stroke cue failed
During every stroke a part moves down into the carriage region. Its colour changes over both shifts: red, blue, or no colour.
The old rule (red pixels > 3 %) only saw the red periods. It found 0 of the 19 day cycles, and at night it also missed
23:48:53–23:59 (a blue period).

- Day colour periods: red 08:37–08:51, blue 08:51–09:08, red 09:09–09:11, blue 09:12–09:37, red 09:38–09:45, blue 09:46–10:18.
- The colour often switches after a longer gap between strokes.

New cue: the carriage plate region (0.345, 0.470)–(0.400, 0.565) compared with its own median picture over ±30 s.
A stroke is a mean grey difference > 12 with a peak ≥ 20. Real strokes peak at 24–43. Other motion stays ≤ 19, with two
exceptions (20.3 with nobody in view, and 21.0).

## Other rule changes (class M1 only)
- The turn to the box is also searched up to 4 frames after the stroke starts. In the day the stroke can start up to 1.4 s
  before the operator reaches the box side.
- The walk back is searched after his right-most point after the stroke (he reaches over the box to its right side).
  The search window is 80 frames (~28 s) after the stroke, up from 40.
- Load: right wrist y ≥ 0.52, or x ≥ 0.50 and y ≥ 0.47. The day operator loads with the hand a little higher.
- Keys renamed: `reach_into_crate` → `reach_into_bin`, `crate_change` → `bin_change`.

## Accuracy (|detector − annotation|, median / max / within 0.5 s)
| element | night (16) | day (19) |
|---|---|---|
| cycles found | 16/16 | 19/19 (old: 0/19) |
| walk_to_fixture | 0.01 / 0.35 / 16 | 0.34 / 0.74 / 13 |
| fixture_work_1 | 0.01 / 0.01 / 16 | 0.01 / 0.45 / 19 |
| reach_into_bin | 0.00 / 2.42 / 15 | 0.01 / 3.27 / 18 (max = bin-change cycle) |
| load_fixture | 0.01 / 0.35 / 16 | 0.01 / 0.70 / 18 |
| two_hand_handling | 0.34 / 0.69 / 14 | 0.70 / 1.06 / 8 (weakest) |
| turn_carry_to_box | 0.00 / 0.01 / 16 | 0.34 / 0.42 / 19 |
| at_box | 0.01 / 0.70 / 14 | 0.01 / 2.28 / 14 (18/19 found) |
| end | 0.01 / 0.35 / 16 | 0.34 / 0.74 / 13 |

## Cycles per hour (old → new, against machine strokes with the operator in view)
| hour | old | new | strokes |
|---|---|---|---|
| 08:00–09:00 | 42 | 83 | 90 |
| 09:00–10:00 | 45 | 252 | 256 |
| 12:00–13:00 | 23 | 56 | 67 |
| night 23:30–00:40 | 163 | 252 | 264 |

- Strokes without a cycle are slow periods with no box visit (08:40–08:44, 12:36–12:42) and two weak strokes.
- In all 35 annotated cycles (night + day), one stroke went with one rail.

## Day vs night
- **Operator:** a different operator, who stands closer to the fixture. He is on the box side 22 % of frames, against 39 % at night.
- **Same work:** the same 7 elements in the same order.
- **Cycle median:** 12.42 s in the day, 13.05 s at night.

| element | day median (s) | night median (s) |
|---|---|---|
| walk back | 0.68 | 1.39 |
| fixture | 2.26 | 2.42 |
| bin | 1.10 | 0.70 |
| load | 0.72 | 1.05 |
| two-hand | 2.83 | 1.74 |
| turn | 0.36 | 1.03 |
| at box | 4.31 | 4.06 |

- Cycle 5 (09:22:09) includes a blue input bin change: 5.4 s.

## Live dashboard count (not changed)
- Camera 1 counts cycles by "part_presence" in the "Part fixture" zone.
- While at the box, the day operator keeps a wrist inside that zone 56 % of the time (night 8 %).
- This likely explains why the live count dropped after 08:40. It is not yet verified.

## Open questions
1. What is the red / blue / plain part in the carriage? Is it a rail variant?
2. What happens in the slow periods with strokes but no box visit?
3. What does he do when he reaches over the box?
4. What starts the stroke?
5. Is one stroke always one rail?
