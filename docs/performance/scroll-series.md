# Scroll series

One line per change, from `tools/performance/scroll_scenario.sh` (real `toad` in `st` on display :121, a fork of `perf-base-20261009`, which is a fork of the saved `agent-comms-ux` session; an active response, held PageUp from the input box, wheel bursts with reversal, End, tab return). Frame work is UI-thread time per frame handed to the driver; input-to-paint runs from the driver posting an event to the first frame after its last handler returns. Input-to-paint pairs each input with the first frame after it is handled (fixed 2026-10-09; earlier summaries paired out of order). Raw results are under `~/.cache/agent-scratch/scroll-series/<name>/`.

| Date | Change | Total frame median (ms) | Total frame p95 (ms) | Input-to-paint median (ms) | Input-to-paint p95 (ms) | Scroll-path lines +/- | What the screen showed |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | Baseline: published default runtime (Toad 312ff42, Textual 73036ff, Core 1a45) | 6.9 | 36.9 | 890 | 2942 | 0/0 | The frame gate withholds the history region for seconds (frames still flow for the rest of the screen, so input-to-paint understates what is seen). The second tab's history stays blank. |
| 2026-10-09 | Branch start: Toad f9b062d, Textual 66e91ec (last committed candidate) | 13.3 | 34.6 | 656 | 2263 | 0/0 | Same. The history scrolls back eventually; End does not return to the tail. |
| 2026-10-09 | Frame gate no longer withholds paint; it only requests preparation for unready visible bodies | 6.3 | 28.2 | 607 | 1885 | 6/33 | 2,914 frames instead of 90; the history visibly moves. Inputs now wait up to 1.8 s in the App queue behind CoreEventMessage handlers of 200–525 ms. |
| 2026-10-09 | Same build, repeated (noise check) | 6.6 | 31.4 | 1174 | 2781 | 6/33 | Run-to-run noise is about 3 ms of frame p95 and about 1 s of input-to-paint p95. |
| 2026-10-09 | App no longer awaits the registry re-read on every coordination event (one background pass at a time) | 6.4 | 32.8 | 995 | 4325 | 17/3 | Slow CoreEventMessage handling gone; wheel bursts still queue about 1.5 s; a few keys took up to 12 s to handle. |
| 2026-10-09 | Same build, repeated | 6.1 | 31.9 | 909 | 2066 | 17/3 | Within noise of the previous build. The UI thread is inside callbacks about 30 of 45 s while executing Python only about 5 s: it is stalled on the GIL and blocking calls. |
