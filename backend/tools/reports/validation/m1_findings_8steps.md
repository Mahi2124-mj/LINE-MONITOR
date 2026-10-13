# Station 1 (Upper Rail Greasing m/c, camera 1): 8-step breakup, 2026-10-12

The 8 steps were given by the process owner and checked frame by frame. Evidence images are in `m1_evidence_20261012/`.

## Data
- **Full-resolution video:** `backend/data/validation_recordings/m1_hd/cam1_hd_20261012.mp4`, 09:37:19.5–09:41:19.3, 1600×900, 12.5 fps.
  - `cam1_hd_20261012_times.csv` holds the frame times.
  - The CSV clock and the 640 recording agree to 0.00 s (±0.04 s).
- **Detector input:** the 640×360 camera-1 recording, 09:35:44–09:41:45, kept in `validation_recordings/cam_1`.
  - Today it ran at about 2 fps: median 0.51 s per frame, with gaps up to 2.9 s.
- **Annotations:** `m1_hd_annotations.json`.
  - 15 consecutive cycles, 09:37:37–09:41:16: 14 normal cycles and 1 with a bin change.
  - Each cycle has the 8 step starts, the cycle end and the stroke on/off.
  - It also has 3 extra events: place in holder, take out of holder, greased rail out.

## What the video shows (one operator; medians relative to the machine stroke S)
| time | what he does |
|---|---|
| S−9.2 | Walk back from the tiger-tape box side. Most cycles, the right hand first takes a thin bent wire part with a white clip from the front-bottom blue bin. |
| S−7.8 | Fixture front: he puts the wire part into the small holder at the end of the yellow bar. Then both hands stay low. Nothing is taken out here. |
| S−6.3 | Right hand into the blue bin behind the fixture. He lifts out a long dark rail. |
| S−5.1 | Right arm reaches over the yellow bar to behind the red column: the rail goes into the greasing position (0.3 s). |
| S−4.85 | Right hand to the second bin and the box under it: the spring support and handle. |
| S−4.0 | Both hands place the parts in the holder. At the same moment the machine makes a short first motion: a slide at the red-column foot, in 13 of 16 strokes. |
| S−3.5 | The parts are taken out of the holder again. |
| S−2.3 | A long dark rail is pulled out along the yellow bar and white roller. |
| S−1.0 | Hands low at the near side of the tiger-tape box: lock bar. |
| S | Machine stroke, 1.35 s. |
| S−0.1 | He assembles with both hands in front of the body. |
| S+2.9 | Arm over the tiger-tape box: the part goes to Station 2. |

**Cycle:** median 13.1 s over the 14 normal cycles (12.3–19.0 s).

**One stroke = one part:** every annotated cycle has exactly one stroke and one hand-over.

## Place vs take-out, and the order
- **The process owner is right: he first places, then takes out.** It happens at the holder, in 15 of 15 cycles: place at S−4.0, out at S−3.5.
  - Example: place 08:59:21.8, out 22.1–22.5, rail pulled out 23.5.
- **There are two rail positions:**
  - the greasing position behind the red column (in at S−5.1);
  - a position along the yellow bar (out at S−2.3).
  - The stroke and the pull change the same nest, so the rail is most likely greased by stroke n and taken out in the next cycle. The rail is hidden during the stroke, so this cannot be followed end to end.
- **The video differs from the list given:**
  - The ~2 s at the fixture front are: wire part in, then hands low. The greased rail comes out later, at S−2.3, inside step 5.
  - The lock bar is taken just before the stroke.

## Steps and accuracy (today, 15/15 cycles found)
| # | key | name | video median (s) | detected (s) | step start error, median / max (s) |
|---|---|---|---|---|---|
| 1 | walk_to_fixture | Walk back to the fixture | 1.62 | 1.32 | 0.12 / 0.47 |
| 2 | fixture_front | Fixture front (wire part in, hands low) | 1.16 | 1.60 | 0.24 / 0.55 |
| 3 | pick_rail | Pick upper rail from the blue bin | 1.15 | 1.32 | 0.22 / 1.18 |
| 4 | load_rail | Put rail on the fixture for greasing | 0.29 | 0.60 | 0.08 / 0.63 |
| 5 | spring_parts | Spring support + handle; greased rail out | 3.88 | 3.53 | 0.23 / 0.59 |
| 6 | lock_bar | Lock bar from the tiger-tape box | 0.90 | 0.75 | 0.44 / 1.19 |
| 7 | assemble | Assemble the parts (machine greases) | 2.80 | 2.53 | 0.38 / 2.82 |
| 8 | hand_over | Reach over the box to Station 2 | 1.03 | 1.00 | 0.11 / 0.58 |

- **greased_rail_out:** found 14/15, error 0.20 / 0.76 s.
- **Stroke on:** found 14/15, error 0.19 / 0.49 s.

## Cycles vs machine strokes
| window | strokes | new cycles | old detector |
|---|---|---|---|
| Today 09:35:44–09:41:45 | 22 | 22 | 18 |
| Today 08:42–09:00 | 69 | 68 | 40 |
| Night 23:30–23:50 | 66 | 64 | 62 |
| Saturday 09:19–09:27 | 36 | 34 | 34 |

## Older validation sets
**Night: 16/16 cycles still found. Saturday day: 19/19.**

Old keys mapped to new keys, median error (s):

| old key | new key | night | day |
|---|---|---|---|
| fixture_work_1 | fixture_front | 0.01 | 0.01 |
| reach_into_bin | load_rail | 0.17 | 0.18 |
| load_fixture | spring_parts | 0.17 | 0.18 |
| turn_carry_to_box | lock_bar | 0.01 | 0.01 |

- The old "reach into bin" was really the reach to the greasing position.

## Open questions
1. Is the rail pulled out at S−2.3 the one greased in the previous stroke?
2. What is the wire part with the white clip? Is it the spring handle?
3. What starts the machine? Its first motion comes 4.0–4.3 s before the stroke, at the same moment as the place in the holder.
4. What happens at the second low visit to the box after the stroke in some cycles?
5. Can the camera-1 recording rate be restored? At ~2 fps a stroke can fall into a recording gap.
