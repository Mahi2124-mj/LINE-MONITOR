# YRA steps 1–3 (camera .30, recorded as camera 8): element breakup, 2026-10-15

Classes `YUR` (step 1 Upr Rail Greasing m/c, station 8), `YHS` (step 2 Handle Supt & Spr Supt Greasing, station 14) and
`YXL` (step 3 Upper Rail X Lock Mecha Assy m/c, station 15) in `station_breakup.py`.

## Data
- **Full-resolution videos:** `validation_recordings/yra_hd/cam8_hd_20261015_2150.mp4` (21:50–21:54) and `cam8_hd_20261015_2244.mp4` (22:44:59–22:49:59).
- **640 recordings:** `validation_recordings/cam_8`, 21:46–22:00 at ~1.6 frames/s and 22:38–23:00 at ~4.4 frames/s.
- **Annotations:** `y??_annotations.json` (13 cycles, low rate) and `y??_45fps_annotations.json` (16–17 cycles).

## Who does what
One operator runs all three machines in a loop of ~13.4 s; his home is the step-2 jig in the middle:
1. The step-2 lamps go off.
2. He picks a rail from the blue bin at the bottom right (step 1).
3. New rail into the greasing opening, greased rail out with the left hand.
4. Back at the step-2 jig: load, parts from the small blue bin, start (lamps on).
5. He walks left to the step-3 nest, swaps the rail, and lays the finished rail on the yellow rack.
6. He walks back to the jig.

- **Step-3 press:** starts ~0.7 s after he leaves and makes two strokes.
- **Step-1 machine:** shows no visible motion.
- **Buffers:** there are none between the steps.

## Steps (median s, 22:38–23:00, 83–84 cycles)
**Step 1 (cycle 13.4)**

| Element | Median (s) |
|---|---|
| Pick from the bin | 0.9 |
| Rail in / greased rail out | 1.6 |
| Unattended while he is at step 2 | 4.4 |
| Unattended while he walks to step 3 and back | 3.8 |
| Unattended until the next pick | 1.8 |

Operator work at step 1 is 2.6 s per cycle.

**Step 2 (cycle 13.4)**

| Element | Median (s) |
|---|---|
| Jig released, waits for him | 2.8 |
| Load + start | 1.6 |
| Lamps on, hands at the jig | 3.0 |
| Walk to step 3 | 1.3 |
| At step 3 | 0.9 |
| Walk back | 1.4 |
| Lamps on, he is back | 1.6 |

**Step 3 (cycle 13.4)**

| Element | Median (s) |
|---|---|
| At the nest | 0.4 |
| Lay on the rack | 0.6 |
| Press (two strokes) | 10.9 |
| Press done, waits for him (in 44 of 84 cycles) | 1.1 |
| Walk over | 1.3 |

## Accuracy (cycles found; step error median)
- **~1.6 frames/s:** 13/13 for each station; most steps within 0.15–0.35 s.
- **~4.4 frames/s:** 17/17, 17/17 and 16/16; most steps within 0.1–0.3 s.
- **Self-check** (per 10 minutes against the neighbouring station): no block left out.
- **Recording gaps:** cycles that span a hole of more than 5 s in the recording are dropped.

## Open questions
1. The step-1 greasing time is not visible, so it is labelled "unattended".
2. What does his right hand do at the step-1 front corner for ~1 s? Possibly a start button.
3. Part of the step-2 "lamps on" time may be the machine waiting for him.
4. Does the far-left person take the rails from the yellow rack?
