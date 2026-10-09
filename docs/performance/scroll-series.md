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

Re-measured on 2026-10-09 with the frame meter fixed (input records had been keyed by `id()`, which Python reuses, inflating every input-to-paint tail above; frame-work numbers were unaffected). All on display :131.

| Date | Change | Total frame median (ms) | Total frame p95 (ms) | Input-to-paint median (ms) | Input-to-paint p95 (ms) | Scroll-path lines +/- | What the screen showed |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | Baseline: published default runtime | 7.1 | 38.1 | 175 | 2951 | 0/0 | As above. |
| 2026-10-09 | Branch start (f9b062d) | 6.3 | 42.0 | 191 | 2485 | 0/0 | As above. |
| 2026-10-09 | After the frame-gate and coordination fixes (b4e08f0) | 5.8 | 30.5 | 53 | 1560 | 23/36 | History moves; per-message widgets still mount and validate paint every frame. |
| 2026-10-09 | Committed history drawn as lines: pages draw their fragments' prepared rows; no widget per message | 2.7 | 8.6 | 7.8 | 20.5 | see commit | History drawn with dividers and bars, no blank rows mid-scroll, End reaches the tail, tab return shows history at once. |
| 2026-10-09 | Same, after deleting the widget-building path and routing lookahead through line preparation | 2.9 | 9.8 | 7.8 | 36.4 | see commit | Same. Within noise of the line above. |
| 2026-10-09 | Published: the five default commands now point at `~/.local/share/agent-comms/runtimes/toad-lines-9eb0042` (Toad 9eb0042, Textual 66e91ec, Core 1a45); measured through the default `toad` | 2.9 | 9.8 | 7.7 | 27.9 | 0/0 | Same as the line above. Frame p99 20.2 ms, input-to-paint p99 40.1 ms: the target is now p99 at or under 16 ms. |
| 2026-10-09 | Line blocks become frontend-neutral (roles, no Rich styles; `toad/line_blocks.py`); strips built once per fragment; pages read their own laid-out width instead of `size` (which forced `reflow_visible` in the lookahead). Two runs; frame p99 16.5 and 19.4 ms | 2.9 | 8.8 / 10.0 | 7.7 | 22.7 / 36.4 | see commit | Same screens. Input-to-paint p99 43 and 63 ms. |
| 2026-10-09 | Live tail drawn as lines (LineMarkdown); body machinery, old Markdown widgets and frame hooks deleted. Back to back with the line above on a quiet bus, two runs each: frame p99 18.8 / 19.4 ms against 17.8 / 18.9 ms | 3.0 | 12.5 / 12.7 | — | 14.2 / 28.0 | +329/−3735 | Same screens. Frame p95 is about 3 ms worse in both runs; input-to-paint p99 22 / 44 ms against 31 / 51 ms. Merged because p99 holds; the p95 cost is next. |
