# Textual fork: Toad terminal presentation WIP (2026-09-23)

**Implementation checkpoint, still Draft; worst <16 ms remains unproven.**
This branch began as a document-only record based on `OpenHCSDev/textual`
`main` at `06dbeef4bb70fb718236aa418ed658ef4667a126`. The September 24
checkpoint below now includes the isolated, reviewed source/test snapshot.
The historical evidence and remaining presentation gate follow it.

This performance PR is separate from the [agent-comms core evidence draft][core]
and [Toad's own UI/recovery WIP PR](https://github.com/OpenHCSDev/toad/pull/1).
`trissim/textual-window` is
neither this Textual fork nor a Toad runtime/package dependency: a Toad menu
docstring credits its interaction pattern only. No fourth PR is proposed.

[core]: https://github.com/OpenHCSDev/agent-comms/pull/1

## September 24 implementation checkpoint

The owner-controlled publication worktree `/tmp/opencode/textual-pr-checkpoint`
contains 15 source paths and 17 test paths imported from the reviewed candidate,
plus this updated evidence document. Frozen running UI source trees are separate.

Included work:
- Lazy bounded Strip caches and prompt release of retired LRU/query/style graphs.
- Focus-rule-aware stylesheet updates, dependency/path/component caches, and
  current-source parsing without the previous 64-source cache thrash.
- Correct displayed/visible child caching, including inherited visibility.
- Scoped, viewport-bounded selection geometry; coalesced derived selection work
  with copy, mouse-up, and paint flush boundaries.
- Compositor geometry validity, inherited-layer lookup reuse, recursive-closure
  release, covered-widget skipping, and exact damaged/exposed vertical paint runs.
- Async Markdown token/prepared-fence hooks and append final-block correctness.
- Timer deadline correction, standards-compatible captured-output `fileno`, and
  typed Linux writer flush notification. A flush is not terminal presentation.

Validation on the publication snapshot: **3065 passed, 1 skipped, 4 xfailed**
using the complete non-snapshot suite (`tests --ignore=tests/snapshot_tests -n 4
--dist loadgroup -q`). Four existing pytest parameter-iterator deprecation warnings.
New compositor regressions first reproduced excess sparse/occluded row rendering,
then checked exact strips/terminal escape parity with scrolling and Unicode.

Bounded native Toad diff fixture, 160×64 cells, 80 iterations per case:

| UI-thread work (not terminal latency) | Earlier candidate | This checkpoint |
| --- | ---: | ---: |
| Requested rows for two damaged lines | 342 | 12 |
| Sparse paint, invalidated styles, median CPU | 32.215 ms | 1.548 ms |
| Sparse paint, warm styles, median CPU | 0.437 ms | 0.523 ms |
| Full paint, invalidated styles, median CPU | 39.328 ms | 38.946 ms |

The sparse optimization removes unnecessary work; it does not solve full-frame
layout/rendering. Timings include composition and terminal escape serialization,
exclude actual I/O/pixels, and are not evidence of meeting the <16 ms gate.
Local fixture: `/tmp/opencode/benchmark-sparse-diff-paint.py`.

### Follow-up: nonrecursive layout measurement

Geometry queries made from a widget's measurement now observe the last committed
map rather than triggering a nested whole-scene rebuild. Presentation caches are
invalidated when the completed new geometry is published. A failed lazy layout
retains its invalidation for a later retry. The focused regression reproduced two
arrangements before the fix and one afterward, with unchanged final geometry.

The profiled sidebar opening removed one nested traversal (566→283 `add_widget`
calls). A larger interleaved sidebar-roundtrip fixture did **not** establish a
general latency improvement, so no whole-sidebar speedup is claimed for this
change. Final complete non-snapshot suite: **3066 passed, 1 skipped, 4 xfailed**.

## Historical September 23 owner intent (before source import)

The Toad terminal UI is expensive under busy streaming conversations, focus
changes, selection, right-sidebar tabs, and cold channel/Recovery opens.
Maintenance's separate **dirty**, uncommitted Textual candidate at
`/tmp/opencode/toad-textual-perf`, branch `perf/strip-cache-allocation` rooted
at `06dbeef…`, had **24 status entries** at 18:48 UTC: 20 tracked modifications
and four untracked tests. The observed touched areas include compositor strip
and cache allocation, NodeList, CSS stylesheet/app-focus dependencies, styles,
selection rendering, Linux writer-thread and driver paths. Tracked diff stats
exclude the four new tests. These are inventory observations, **not** reviewed
source in this document's PR, upstream `Textualize/textual` changes, or an
authority to stage all dirty paths.

Owner-reported development evidence: a 60-second active multitab/focus profile
recorded 5,164 samples with no reported errors and found app-focus restyling a
large inclusive cost. Interleaved same-scene **headless** focus transitions
were reported to improve ~245.46 ms median / 271.3 ms worst to 14.05 ms median
/ **17.61 ms worst** after candidate focus/dependency changes; 3,035 Textual
tests were reported passing on an owner-local candidate. These are not
independent stopped-byte PR results, and **even the headless worst is above
16 ms**. Historical Toad cold useful terminal pixels roughly 197–366 ms and
streaming/GC spikes remain above 16 ms. A successful trivial scene, `_display`
timing, PTY writes/queues, median, or headless rendering never proves the
strict terminal-presented worst-frame requirement.

## Original source/performance gates

The import and test steps below describe the original document-only gate. The
September 24 source import and test checkpoint is recorded above; terminal-pixel
performance, production integration, and release review remain outstanding.

1. Owner `opencode-toad-maintenance` must stop current source/test edits,
   identify the complete exact attributable Textual subset against remote
   `main`, freeze hashes and scope, and authorize a separate isolated writable
   branch. Independently review compositor/style/focus/selection/writer
   semantics and all new tests before importing any code. Do not stage moving
   `perf/strip-cache-allocation` or the 24 dirty paths wholesale.
2. Re-run focused cache/focus/CSS/compositor/selection/strip/writer regression
   tests and representative Textual suite on those frozen bytes. Check
   rendering/pixel parity, selection, clipboard/history/input, writer fault
   handling and any OS-dependent behavior. Passing tests alone do not prove a
   terminal timing target.
3. In a separately reviewed compatible pinned Toad, collect repeatable
   **worst completed semantic frames actually presented as pixels by a real
   terminal emulator** over busy streaming, scrolling, selection, tab/sidebar,
   channel opens, and Recovery. Record per-scene maxima, instrumentation,
   emulator/machine and failures. Strict **worst <16 ms is currently FAIL /
   unproven**. If still above threshold, keep Draft and report bottlenecks
   rather than declaring success from the headless 17.61 ms observation.
4. Keep protocol correctness and UI responsibilities in their own repositories.
   Do not weaken agent-comms durable claims, add per-paint bus scans/fsync, or
   turn on publication/monitoring/retry/`SILENT` to improve a benchmark.

This draft does not change Toad's dependency pin, provide a production rollout,
or authorize a merge. Source publication does not close the performance gate.
