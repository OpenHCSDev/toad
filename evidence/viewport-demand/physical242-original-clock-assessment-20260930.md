# Original recorder clocks and diagnostic separation

Read-only Kepler contribution to Heisenberg245. Uses existing release02 and242 profiles, original source, physical phase artifacts and kernel counters only. No new app/capture/provider/native input, clock producer, resource cache or semantic store. Parent corrected “NativeProxy” as a wrong term: no such owner/artifact is asserted.

## Clock contracts actually present

- `record_installed_tui.profile_launch`: Python `time.monotonic()` sampled immediately before execing the profiler. Original UI PID and process birth are retained. `record` observes the profiler's Sampling-process line later in that same host monotonic domain. The original nominal profiler-origin bracket is35.2–79.1ms wide in these runs; sampling cadence adds40ms. The resulting nominal uncertainties are57.6ms for242 and79.6ms for02.
- `record`: `capture_launch_monotonic` is sampled **after** starting FFmpeg. It is an action epoch, not the timestamp of first X11 frame acquisition. No original first-frame monotonic witness exists. Therefore profiler-origin uncertainty does **not** bound absolute video-frame alignment; it cannot certify a50ms frame or key-to-paint claim.
- `mark`: ordinary phase timestamps are taken before kernel-counter census, screenshot and DTO export. For the B-ready marker, they are replaced after the visible-history wait finishes. Markers do not record exact injected-keystroke timestamps. Marked phase duration includes observer work and physical helper/settle time.
- `capture_loaded_state`: started_seconds/finished_seconds bracket the original capture-live invocation in the same recorder monotonic domain. These support identifying observer-overlapping sampled stacks, not observer CPU subtraction.
- `capture_live`: manifest started_ns/finished_ns use Unix wall `time.time_ns()`. `capture_state`: captured_ns is also Unix wall; ui_capture_ms is a duration in its own original Python monotonic domain. Do not treat the Unix nanosecond fields as Node hrtime or use a later clock sample to create a historical binding.
- `capture_state` visible-history wait measures task entry to native FrameFlush writer acknowledgment and readiness recheck. Original B242 elapsed2144.371ms versus02 elapsed2750.491ms is that duration, **not** roster-click to first physical paint.
- `/proc/PID/stat` with original birth ticks supplies phase CPU deltas. Neither Chrome transition lengths nor group counts are CPU durations.

Sources: tests/tools/record_installed_tui.py (profile_launch, record, mark, capture_loaded_state), tools/performance/capture_live.py and tools/performance/capture_state.py. Their source/receipt identities remain original; only this diagnostic interpretation changed.

## Derived original-clock assessment

The JSON companion expands each changed-stack timestamp using its original nominal profiler-origin bracket plus sampling interval. A phase-boundary crossing remains ambiguous. Any interval intersecting a recorded capture invocation remains observer-overlapping. Queries for diagnostic, layout/paint and history/preparation sources overlap and must not be added together. This is an offline projection of original observations, not an additional phase authority.

For242, Down includes43 layout/paint and28 history/preparation changed-stack groups wholly outside both observer and phase-boundary ambiguity. Idle includes9 layout/paint and35 history/preparation groups; A-return includes4 and19 respectively. Diagnostic-source matches all lie inside ambiguous observer intervals. This supports continued investigation of actual product work: the remaining idle/preparation activity cannot all be dismissed as DTO export. It still does not allocate CPU time to individual mechanisms or establish request/provider causality.

Both physical workflow gates remain16/16 passed. End/idle readability, source/window/reader/draft/Undo retention and original owner/source preservation use native records and inspected physical endpoints; these do not depend on a50ms timing oracle. The50ms/resource/foreground targets remain Heisenberg245 scope.

Raw: /home/ts/.cache/agent-scratch/kepler242-physical-review-20260930/native-observer-clock-assessment.json. Original captures and failed broad-path-filter assessment remain protected. No repeated capture is required to preserve these limits.
