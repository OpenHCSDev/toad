# Scroll series

One line per change, from `tools/performance/scroll_scenario.sh` (real `toad` in `st` on display :121, a fork of `perf-base-20261009`, which is a fork of the saved `agent-comms-ux` session; an active response, held PageUp from the input box, wheel bursts with reversal, End, tab return). Frame work is UI-thread time per frame handed to the driver; input-to-paint runs from the driver posting an event to the first frame after its last handler returns. Raw results are under `~/.cache/agent-scratch/scroll-series/<name>/`.

| Date | Change | Total frame median (ms) | Total frame p95 (ms) | Input-to-paint median (ms) | Input-to-paint p95 (ms) | Scroll-path lines +/- | What the screen showed |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | Baseline: published default runtime (Toad 312ff42, Textual 73036ff, Core 1a45) | 17.4 | 91.1 | 6116 | 13742 | 0/0 | Nothing moved for the whole run: no scroll, the typed message never appeared, End did not reach the tail. 132 frames in 45 s. The second tab's history stayed blank. |
