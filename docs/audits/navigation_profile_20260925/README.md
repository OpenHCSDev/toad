# Navigation profiling checkpoint — 2026-09-25

The user authorized merging this checkpoint **despite stalls above 30 ms**.
This is a measured intermediate improvement, not completion of the 16 ms goal.

## Reproducible captured implementation

- Toad `a78ddcc` plus removal of the 16-line immediate frame-request block in
  `SideBar.toggle`; the queued request remains.
- `side_bar.py` SHA-256:
  `7dccbc0a09e84fa8b63e4488cace52e48510e41e9184e1fc1522f9e36792870f`.
- Textual `84db46421b58c33b1de7edea1fa39a7e9401e22d`.
- Installed agent-comms `71b697743f18c8cdc440308e58f7686645d8958e`, Python 3.14.2.
- Persistent worker renderer; existing real server and saved histories. No
  prompts or provider turns were sent by the workload.
- Subsequent integration of main is correctness-tested separately; these
  measurements belong to the captured implementation above.

## Completed real-desktop run, no py-spy

70 guarded actions at **307×81 cells**, ten native tabs: three additional opens
from seven already open, reverse/forward revisits, ten 36-wheel deep-scroll
bursts, eight category toggles on loaded history, and two selection-scroll
gestures. The first retained page moved from byte offset 89,957,453 to 88,879,480;
the bounded retained set reached 144 fragments and evicted newer fragments.
All filters returned to their original values. UI checks completed without an
application crash. This is broader and larger than the former three-tab,
113×42-cell workload; **do not compare their maxima as a controlled speedup**.

| Observed boundary | Median | p95 | Max |
| --- | ---: | ---: | ---: |
| Loop wakeup gaps ≥5 ms | 22.09 ms | 143.86 ms | **519.40 ms** |
| Layout calls | 21.71 ms | 127.81 ms | 399.32 ms |
| Compositor-refresh calls | 11.30 ms | 31.57 ms | 61.22 ms |
| GC calls | 0.00 ms | 0.93 ms | 295.84 ms |

These are instrumented wall-clock spans, not terminal-pixel frame durations.
The filtered gap distribution excludes ticks below 5 ms. Nested spans overlap.
Earlier interrupted attempts are excluded from this completed run's summary.

## Isolated terminal run with py-spy

The same workload categories ran against the real server using `st` on a
dedicated **Xvfb display**, without desktop input or focus interference.
75 guarded actions completed, including nine opens from a fresh single-tab UI,
ten native tabs, reverse/forward revisits, deep paging, filters, and selection.
The actual terminal was **306×80 cells**. This differs in starting history and
font geometry from the real-desktop run and is not a matched overhead estimate.

`py-spy 0.4.2 record --rate 100 --idle --format speedscope --duration 180`
collected **763,001 all-thread samples, zero sampling errors**. Sampling includes
idle stacks and observer activity. The main thread has 17,999 samples. Sampled
Python stacks are not a complete native CPU trace or a frame-latency metric.

| Observed boundary under profiling | Median | p95 | Max |
| --- | ---: | ---: | ---: |
| Loop wakeup gaps ≥5 ms | 17.25 ms | 140.09 ms | **874.41 ms** |
| Layout calls | 32.22 ms | 168.14 ms | 805.44 ms |
| Compositor-refresh calls | 16.24 ms | 50.04 ms | 139.36 ms |
| GC calls | 0.00 ms | 0.00 ms | 237.16 ms |

The worst layout's 805 ms wall duration contained 256 ms of UI-thread CPU time;
sampling and scheduling overhead are material. Use the no-py-spy run for the
current responsiveness observation and this capture for attribution.

### Granular artifacts

- `navigation.speedscope.json.gz`: all sampled stacks, with local file prefixes
  normalized. Decompress and open in https://www.speedscope.app/.
- `actions.json`: each action interval, its observer timing distribution, and
  its top inclusive main-thread sample stacks. The sample alignment uses
  profiler launch time; attachment offset is not measured, so this attribution
  is approximate. Observer spans use exact monotonic timestamps.
- Generator: `tests/profile_navigation_capture.py`. No transcript text or
  screenshots are included in the published artifacts.

### Follow-up priorities supported by the capture

Across the full 180-second capture, inclusive main-thread samples total:

| Function / phase | Sampled seconds |
| --- | ---: |
| Selector idle | 96.94 |
| `_refresh_layout` | 30.78 |
| `reflow` | 17.24 |
| `render_update` | 14.68 |
| `_switch_mode_ready` | 5.62 |
| `reflow_visible` | 2.68 |
| `_present_snapshot` | 2.60 |

These categories overlap. Exclusive main-thread hotspots include parent lookup,
reactive reads, compositor traversal, stylesheet rules, and DOM/CSS ancestor
walks. Worker threads already perform `viewer_snapshot` and registry reads;
their inclusive lock stacks also include waiting and must not be called CPU
cost. The renderer subprocess was not separately sampled by this PID capture.

The next performance iteration should prepare older/newer history farther ahead
in workers using a substantial **bounded immutable-page buffer**, while measuring
UI-thread installation independently. Widget construction/mounting, style
application, geometry, anchor compensation, and GC still need bounded work and
fewer invalidations; simply enlarging a worker queue will not remove those costs.
Retain anchor/input revision, filtering, cancellation, memory bounds, and visible
read-acknowledgement correctness. Do not disable GC or hide genuine invalidation.

Also deferred: shared recognition/highlighting of `@thread_name` in ordinary
text, not only routed-message decorations.

## Integration validation

Integrated main through `447600d` (PR #33), preserving its agent-comms pin
`74e157e116858f485badc1d083df5342dcca0686`. Textual PR #2 is merged at
`06220c3837e8df0cb140b2d64205a0766398c9dc`, which is now the Toad pin.
Backend validation used a dedicated test environment; the shared stack was not
updated. Fresh framework checks passed **21 tests**; the prior complete
non-snapshot-directory run passed 3,087 with 1 skip and 4 expected failures.

**18 Toad integration pilots passed**: pointer focus, opening continuity,
sidebar projection, history scroll-frame anchoring, categories, human read
boundaries, broad Comms, pending-thread metadata, many-tab revisits, worker
previews, replay worker gating, context disclosure, context resume, compaction
progress, transcript teardown, multipart Markdown, automatic compaction
visibility, and send-now failure handling. Fatal Ruff and whitespace checks pass.

One history-anchor run timed out during a combined run; isolated runs passed both
with and without the optional persistent-renderer dependency path. This is not
reported as an uninterrupted all-green combined command.

An inherited goal-pause pilot fails because the pinned core's `Goal` lacks
`paused_by`. It fails identically on clean main `447600d` with main's own pinned
dependencies. This pre-existing core/test-contract mismatch is outside this
performance change; no goal behavior was changed to make the test pass.
