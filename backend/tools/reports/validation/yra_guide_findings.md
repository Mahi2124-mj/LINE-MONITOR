# YRA steps 4–5 (camera .32, recorded as camera 9): element breakup, 2026-10-16

Classes `YG1` (step 4 Guide S/A Insert #1 m/c, station 9) and `YG2` (step 5 Guide S/A Insert #2 m/c, station 10) in
`station_breakup.py`.

## Data
- **Full-resolution videos:** `validation_recordings/yra_hd/cam9_hd_20261015_2155.mp4` (night) and `cam9_hd_20261016_0928.mp4` (day).
- **640 recordings:** `validation_recordings/cam_9`, night at ~1.5 frames/s and day at ~4.5 frames/s.
- **Annotations:** `yg?_annotations.json` (night, 8 cycles each) and `yg?_5fps_annotations.json` (day, 19 cycles each).

## Who does what
One operator runs both machines in a loop of ~26.5 s, one rail at each machine per loop. At each machine:
1. Green guide parts from the two teal bins.
2. Finished rail out and laid in the upper yellow comb of the rail stand in front.
3. Next rail from the lower bars of the same stand.
4. Rail into the machine, more guide parts.
5. Walk to the other machine.

Machine cues:
- **Step 4:** a green lamp at its carriage, lit ~12 s per cycle. It starts 2.4 s after he leaves at night and 1.4 s in the day.
- **Step 5:** a slide in front of a green-lit plate. It is home again 7.5 s after he leaves.

## Steps (median s, 22:40–10:30)
**Step 4: 742 cycles, cycle 26.7 s**

| Element | Median (s) |
|---|---|
| Guide parts | 4.5 |
| Rail out to the stand | 0.8 |
| Lay in the comb | 0.7 |
| Next rail back | 0.9 |
| Rail in + parts | 3.5 |
| Start delay | 2.4 |
| Machine (lamp) | 12.0 |
| Machine waits for him | 1.9 |

He spends 11.0 s per cycle at this machine.

**Step 5: 807 cycles, cycle 26.5 s**

| Element | Median (s) |
|---|---|
| Guide parts | 4.7 |
| Rail out | 0.6 |
| Lay in the comb | 0.7 |
| Next rail back | 2.1 |
| Rail in until the slide moves | 2.1 |
| Parts, then leave | 2.0 |
| Machine after he leaves | 7.5 |
| Machine waits for him | 6.2 |

He spends 12.8 s per cycle at this machine.

Both machines mostly wait for the operator; he rarely waits for a machine.

## Accuracy
- **Night (~1.5 frames/s):** 8/8 cycles for each station.
- **Day (~4.5 frames/s):** 19/19 for each; step error median 0.05–0.20 s, max 0.58 s.
- **Day set thinned to every third frame:** also 19/19.
- **Self-check** (per 10 minutes, step 4 against step 5): only blocks with a recording gap or the line starting / stopping were left out.

## Open questions
1. Do the two machines work in series or side by side? Both take rails from the same lower bars and lay them in the same comb.
2. Who fills the lower bars, and which station is the bottom-left person who takes rails from the comb?
3. What changed the step-4 start delay from 2.4 s at night to 1.4 s in the day?
