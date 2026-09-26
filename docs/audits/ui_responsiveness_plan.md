# UI responsiveness tracking plan

Status: **draft implementation and investigation; performance targets unmet**.
The branch includes the current Toad implementation, regression pilots, audit,
and the [debug/capture/replay toolbox](../../tools/performance/README.md).
Textual changes are tracked in [companion draft PR #5](https://github.com/OpenHCSDev/textual/pull/5).

## Locked-in issues

The four confirmed causes:

1. [Textual #4](https://github.com/OpenHCSDev/textual/issues/4): long-lived reactive
   publishers retain retired subscriber widgets/callbacks. The aged live capture
   contained2,268 closed FooterKey subscriptions on Footer.compact.
2. [Toad #59](https://github.com/OpenHCSDev/toad/issues/59): synchronous filter
   invalidation traverses message descendant trees for a display-only change.
   A captured-data Thinking setter used about185ms of UI-thread CPU.
3. [Toad #60](https://github.com/OpenHCSDev/toad/issues/60): owner/goal polling
   reconstructs coordination services and loads/decodes registry data on the UI
   thread. Two live profiles show this as a substantial foreground path.
4. [Toad #62](https://github.com/OpenHCSDev/toad/issues/62): filter supersession
   during awaited mounts can crash or publish stale rows/cursors.

Additional requirements are first-class work items:

5. [Toad #61](https://github.com/OpenHCSDev/toad/issues/61): unload transcript
   widget trees far outside the viewport and lazily reload canonical history;
   prepare filtered data/views on workers. Source size must not dictate
   steady-state UI cost. Include non-tail and inactive-tab live accumulation.
6. [Toad #64](https://github.com/OpenHCSDev/toad/issues/64): paint-only thinking
   spinners and a high-frame-rate foundation for future effects.

## Budgets and acceptance

- Target 16.7 ms steady-state frame work for 60 Hz animation. Current throbber cadence
  is 30 Hz; timing its renderer is not proof of delivered 60 FPS.
- 200 ms UI-thread stops are failures, regardless of whether a test eventually
  completes. Report p50/p95/p99/max and input acknowledgment, not only averages.
- Loading and spinner feedback are allowed; typing, navigation and cancellation
  must remain available while slower work completes.
- Measure cold-open loading feedback, target-mode terminal flush, content-ready
  completion and warm switching separately.
- Scale transcript source size10x/100x while bounding mounted widgets and cached
  bytes. Preserve anchors, selection/copy, live arrivals and visible-only reads.
- Exercise all seven filters across multiple threads, all-off/restore, rapid
  toggles, blocked reads/mounts, closing and switching, and unsent draft typing.

## Current implementation progress

### Toad

- Compact worker identities/results for sidebar projections and shared
  serialized preparation storage with independent worker-delivered values.
- Reuse coordination readers and move cold owner lookup/construction off-loop.
- Viewport-based mounted history budgets, selected/anchor protection, and
  targeted viewport geometry through the Textual companion.
- Worker-prepared user Markdown; Markdown declares measured child extents as
  output rather than triggering redundant ancestor measurement.
- Hidden/absent goal documents avoid forcing full-tree geometry on resize.
- Resize handles/sliders opt out of accidental text selection and its full-tree
  traversal during pointer capture.
- A shared first-presented-frame startup boundary for session views, sidebar
  source refresh and conversation startup. Close/cancel checks preserve ownership.
- Filter publication retains its own overlay and rechecks generation after
  awaited mounts; stale work cannot advance the new filter cursor. Empty masks
  stop pointless older-history scans and lookahead.
- Display-only filtering opts into the stylesheet's dependency check; custom
  descendant/inherited CSS retains the ordinary subtree path.

### Textual companion

- Retire obsolete box-model cache generations; targeted anchor geometry for
  viewport layout; measured-extent policy with unchanged defaults.
- Lazy optional DOM/message storage, shared immutable selector metadata.
- Timer callback/task cleanup and closed presentation/cache cleanup.
- Avoid unused message signals and idle retention of processed payloads.
- Subscriber-owned reactive cleanup with weak publisher tracking.
- Parsed-declaration query for local display-only class invalidation.

## Evidence and limitations

- Full Textual suite at the latest framework checkpoint:3128passed,1skipped,
  4xfailed, excluding snapshot tests. The packaged Toad pilot runner passes49cases.
  Toad broad and focused receipts are detailed
  in the audit; regression failures were reproduced before the relevant fixes.
- All-seven-filter four-thread stress reproduced a real mount-supersession crash.
  After the fix it completed72actions and applied52/52typed markers to the correct
  drafts. Remaining input/stall outliers around200ms are **not** accepted as done.
- The portable-toolbox repeat also completed72actions/52typed markers with all
  masks restored; input acknowledgment still reached217ms. It is recorded as a
  passing workflow with failing performance, not a responsiveness success.
- Live sampling and DTO capture succeeded. The saved live workload was replayed
  headlessly in an isolated store across13views. It exposed costs absent from the
  small synthetic fixture, including hundreds of direct live blocks in one view.
- **Observer correction:** early navigation wrappers lost Textual decorator
  identity and dispatched transcript/ready handlers twice. A failing-before
  observer check now enforces one dispatch. Affected captures and the quoted
  740–850ms opening range are not valid acceptance baselines.
- Corrected first-frame policy comparison showed median target-mode flush about
  780ms (ungated control) versus691ms (gated), with content-ready medians about
  814/827ms. This is partial progress, not the target or proof of faster loading.
- Local display invalidation has semantic coverage, but one real-data replay
  had a 34 s wall/1.3 s CPU setter outlier. A later host check showed full swap,
  but the cause of that discrepancy remains unresolved. Keep that result visible
  and repeat with resource attribution before claiming a gain.
- The captured replay is loaded data/view state, not a full process checkpoint;
  the first bundle incompletely captures transient tool/live input metadata.
- The branch was developed from an older main revision. Integrating newer main
  changes is required before merge. The draft pins the tested core revision and
  Textual companion commit so the declared API dependency is explicit.
- A minimal306x80 headless spinner probe requested60Hz and recorded180updates in
  3seconds: frame-work p951.14ms/max2.23ms, zero layout/CSS-apply calls. That is
  component/compositor evidence, not a delivered-terminal-FPS or loaded-app claim.

## Next work

1. Quantify reactive-retention cleanup under aged/captured interaction churn.
2. Attribute the remaining filter pause to setter, allocation/GC, layout, paint,
   GIL and host scheduling separately; bound work rather than move the stall.
3. Complete worker-side filtering and source-size-independent presentation,
   especially direct live blocks when scrolled away from the tail.
4. Establish spinner steady-state frame-work and input budgets on the same load.
5. Repeat unprofiled real-terminal acceptance after correctness and source/receipt
   checks, then integrate the companion framework and current main.
