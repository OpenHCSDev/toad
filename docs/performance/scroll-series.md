# Scroll series

One line per change, from `tools/performance/scroll_scenario.sh` (real `toad` in `st` on display :121, a fork of `perf-base-20261009`, which is a fork of the saved `agent-comms-ux` session; an active response, held PageUp from the input box, wheel bursts with reversal, End, tab return). Frame work is UI-thread time per frame handed to the driver; input-to-paint runs from the driver posting an event to the first frame after its last handler returns. Raw results are under `~/.cache/agent-scratch/scroll-series/<name>/`.

| Date | Change | Total frame median (ms) | Total frame p95 (ms) | Input-to-paint median (ms) | Input-to-paint p95 (ms) | Scroll-path lines +/- | What the screen showed |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | Baseline: published default runtime (Toad 312ff42, Textual 73036ff, Core 1a45) | 6.9 | 36.9 | 7502 | 16007 | 0/0 | Inputs are handled within milliseconds, but the frame gate withholds paint for seconds. The second tab's history stays blank. |
| 2026-10-09 | Branch start: Toad f9b062d, Textual 66e91ec (last committed candidate) | 13.3 | 34.6 | 33147 | 36767 | 0/0 | Same. The history scrolls back eventually; End does not return to the tail. |
