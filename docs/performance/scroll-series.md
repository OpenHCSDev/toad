# Scroll series

One line per change, from `tools/performance/scroll_scenario.sh` (real `toad` in `st` on display :121, a fork of `perf-base-20261009`, which is a fork of the saved `agent-comms-ux` session; an active response, held PageUp from the input box, wheel bursts with reversal, End, tab return). Frame work is UI-thread time per frame handed to the driver; input-to-paint runs from the driver posting an event to the first frame after its last handler returns. Input-to-paint pairs each input with the first frame after it is handled (fixed 2026-10-09; earlier summaries paired out of order). Raw results are under `~/.cache/agent-scratch/scroll-series/<name>/`.

| Date | Change | Total frame median (ms) | Total frame p95 (ms) | Input-to-paint median (ms) | Input-to-paint p95 (ms) | Scroll-path lines +/- | What the screen showed |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | Baseline: published default runtime (Toad 312ff42, Textual 73036ff, Core 1a45) | 6.9 | 36.9 | 890 | 2942 | 0/0 | The frame gate withholds the history region for seconds (frames still flow for the rest of the screen, so input-to-paint understates what is seen). The second tab's history stays blank. |
| 2026-10-09 | Branch start: Toad f9b062d, Textual 66e91ec (last committed candidate) | 13.3 | 34.6 | 656 | 2263 | 0/0 | Same. The history scrolls back eventually; End does not return to the tail. |
| 2026-10-09 | Frame gate no longer withholds paint; it only requests preparation for unready visible bodies | 6.3 | 28.2 | 607 | 1885 | 6/33 | 2,914 frames instead of 90; the history visibly moves. Inputs now wait up to 1.8 s in the App queue behind CoreEventMessage handlers of 200–525 ms. |
