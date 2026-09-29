# Workspace lifetime implementation — PR116

Implementation is in progress. Workspace-wide navigation and the blank-session
editor now have one application owner each. Agent-backed sessions and the native
per-mode screen shell still retain their rich view and are not bounded globally.

## Completed component in this checkpoint

- `WorkspaceChrome` owns one header and one Channels presentation.
- Nominal `WorkspaceProjection` implementations supply slot/source/activation
  behavior. View types declare locations instead of constructing global controls.
- The previous SharedChannels owner is removed; callers use the workspace owner.
- Native, pending, history/channel and file views share header identity. Slotless
  views park it. Source binding and destination retirement checks precede transfer.
- Conversation composition and AgentReady no longer start an unused shell. Its
  existing owner starts on real shell use, including the actual first-use command.

The next source-compatible slice introduces a nominal `SessionPresentation` with
`RetainedSessionPresentation` for executing agents and `BlankSessionPresentation`
for sessions without an execution owner, persisted session identity, or initial
prompt. These are chosen at the declared session construction boundary. The
blank controller stores the actual editor document, undo/redo, selection, filter,
history and scroll intent through the companion native TextAreaState API. One
`BlankSessionSurface` transfers one `Conversation` between blank tabs. If actual
shell/agent/content/input activity arises, it leaves that surface with its owner
and creates another blank editor for future tabs. When switching to a nonblank
view, it parks the shared presentation on an inert application-owned screen;
screen-specific window/viewport subscriptions transfer with the widget. Blank
right-panel content mounts on first reveal; its per-tab sidebar state remains the
authority, not a global copy. This work does not stop an Agent to save UI memory.

`WorkspaceChrome` also owns one binding-aware Footer. Its nominal projection
rebinds the native screen binding signal on transfer and requests the selected
`Screen.active_bindings` from the Footer's own message pump. There are no
FooterKey actor remounts between same-binding blank tabs. Screens declare a
`FooterSlot` and their compact preference; Store retains its separate Footer.
Directly invoking binding reconciliation in the app's switch context failed the
native reactive binding context assertion before this owner-correct dispatch.

This stage still transfers chrome between existing mode screens. It is not the
final persistent WorkspaceScreen topology and does not claim all rich UI is
globally bounded. Unused shell resources are demand-activated as described above.

## Current validation

Base: current main6662485, including watcher109/113 and pending unread112. Exact
core492e26de354df6fe020ca69b55fdcd92fb06778e; Textual16ede007 during these runs.

- Ownership/resource guards and the cross-view/shared-source pilot pass.
- Eleven focused navigation/sidebar/first-frame/ownership cases pass in48.31s;
  peak305.9MiB, zero swap, one worker.
- Strict16-tab empty probe: one strip,17labels/17close buttons,2,280registered
  widgets; first-return median40.24ms/max52.51ms. Warm medians43.03/43.62ms,
  max63.27ms. Four reflows remain. This probe preceded the lazy-shell change.
-64-tab probe with the lazy-shell change reached its240s runtime limit and did not
  produce a completed receipt. Peak330MiB, zero swap. Its phase/idle/teardown delay
  needs diagnosis; this is explicitly not passing scalability acceptance.

Subsequent tests, each kept distinct from that source and from the old core:

- A first attempt retired/mounted every inactive blank Conversation. Its fail-
  before lifecycle regression passed after implementation, but the16-tab median
  rose to **180–187ms**, all45 switches over100ms. That mechanism was removed;
  swapping editor state in one retained widget replaces it.
- A first shared-editor attempt cleared the departing editor's **same** undo
  history with `load_text`; the native undo test failed, then passed only after
  new logical sessions received independent Document/EditHistory objects.
- With shared editor before right-sidebar deferral, strict16-tab fixture retained
  only **two Conversations and two PromptTextAreas** across17 logical sessions,
  1,215 registered widgets. No replaced channel rows/stale tab frames. Warm
  median70–75ms; still too high for the user's steady-state target.
- Right-sidebar deferred-mount policy initially exposed partial controls during
  layout: `#sidebar-left` was absent. The normal layout path now reconciles
  controls only when the child tree is mounted and retries after refresh. Focused
  right-sidebar/user-reveal checks passed (unit `toad-blank-sidebar-focused-2`).
- With blank right panels mounted only when revealed, **strict64-tab full**
  `many_tabs_return_pilot` (three visit phases, resize, same-mode request, close
  checks, ordinary GC) passes in **52.23s** under the unchanged240s diagnostic
  ceiling. One header/65 labels/65 close buttons,2 Conversations,1,402 widgets,
  ~348k tracked objects; earlier pre-workspace64 probe retained16,993widgets and
  >2m tracked objects, on a different core revision. First-switch median/max
  80.15/100.21ms, warm87.38/119.67 and86.43/107.60ms. Worst GC6.01ms; worst
  loop gap125.89ms. First phase1/63 switches >100ms, warm forward13/63, third2/63.
  This is a large memory/GC improvement, **not** the requested stable30–40ms
  or a universal worst-case fix. The baseline comparison is structural, not a
  controlled same-core latency comparison. Native validation and long-lived
  agent-backed session scaling remain pending.
- One-footer strict16-tab run: **one** Footer, one tab strip,17 labels,
  two Conversations,536 registered widgets, zero FooterKey mounts and three
  reflows per switch. First/warm switch medians ~73/72/70ms; third-pass max
  102.19ms. No stable30–40ms claim.
- Deferred right-panel mount initially created a stale `CoordinationStatus` when
  a session identity arrived before first reveal. The panel now invokes its
  owner-provided `on_hydrated` callback after mounting; `MainScreen` binds the
  current actor/root to status, recovery and relationship presentations. Visual
  tests reveal the panel before checking its actual displayed status while
  retaining the hidden-source-no-read assertion. A long `comms_pilot` attempt
  failed because `os.waitpid` observed an already-reaped external process; the
  unchanged semantic test passed on the immediate serial retry (~61s).

Additional correctness: native window/DocumentViewport screen-local subscriptions
are rebound on reparent and old-screen paths are explicitly released. The
cross-view lifecycle pilot verifies one widget/task, the real editor document
and undo, selection, separate drafts, file/store parking, and that first shell
use promotes its real execution view rather than moving it to another session.
It also checks crossing two different project roots: the same widget's source
path, real DirectoryWatcher root and prompt-history scope follow the selected
session through `Conversation.sync_project_path`, then return to the first root.
Updating just the reactive path left the previous watcher subscribed and was
rejected as an incomplete presentation swap.
One normal long focused run passed25 cases then failed a now-invalid assertion
that a blank inactive tab still contained a Conversation; its corrected semantic
check and later12 targeted cases passed. Tests of current MainScreen source
authority are not weakened to claim that a running Agent can be evicted.

The native editor handoff dependency is [Textual #8](https://github.com/OpenHCSDev/textual/pull/8).
It preserves actual document and undo/redo identity across presentation transfer;
**3,515 framework tests pass**,1skip/4xfail in207.61s on that exact source.
Toad pins its feature head; its complete suite still needs a fresh result on
the latest integrated Toad/core revisions.

Toad main advanced to #107 (`df0a758`) while the above fixed-base probes ran.
That integration updates core from492e26d to its paired nominal/L0A revision.
This branch has now incorporated #107 and pins its current core revision
`2bfbdb23ed1eaf39238d84e18c386a707e9a6f6e`, while retaining the
Textual editor-state feature head `d9def32f`. `toad-workspace-l0a-smoke` passes
the blank editor, shared Channels/footer, right Comms, typed settings and L0A
caller guard cases on the isolated new-core environment (five pilot cases;
24.39s/316.1MiB peak/zero swap). Complete-suite and native rendering acceptance
on that merged combination remain outstanding. The measurements above remain
labeled with their actual earlier source/core.

## Exact current-main/core results after #107

- `toad-workspace-l0a-scale64.json`: strict empty64-tab headless run completes
  three phases, resize, same-mode request, route reconciliation and closes in
  **45.43s**, peak185.5MiB, zero swap. Exactly one header, one Footer, one
  Channels tree,65 labels/close controls, two Conversations and1,208 registered
  widgets. First/warm switch medians77.94/78.24/80.48ms. One of189 switches
  exceeded100ms (first revisit102.94ms); maximum loop gap106.20ms, maximum GC
  3.92ms. No stale tab frames or replaced channel rows. Still above the desired
  stable30–40ms and not proof for loaded/agent-backed 64-tab sessions.
- `toad-workspace-l0a-native-nav`: **83 actual terminal actions / 10 tabs / 8
  sidebar resizes**, four channel identities each singleton across all modes;
  scope peak538.9MiB, zero swap. Native loop gap max131.56ms, GC max101.62ms,
  layout max86.17ms. These tails remain adverse despite the blank-session GC
  improvement. Owned capture scope stopped after the memory receipt.
- `toad-workspace-l0a-native-filters`: **72 native actions, seven categories,
  four restored masks/drafts,52/52 input markers**. Input median/p95/max
  38.34/58.96/70.80ms; loop max106.25ms, GC max86.88ms (UI-thread max74.84ms).
  Scope peak493.9MiB, zero swap; stopped. Strict native feature coverage passes;
  the worst-case and input targets do not.
- Source/host readiness separated at `CommsSidebar._finish_navigation`: after
  source reconciliation, a whole-screen native reflow occurs only if geometry
  was actually invalidated. Matched current-core strict16-tab blank probes pass
  with **two** reflows instead of three, switch medians64.10/66.68/67.23ms;
  strict64-tab source on the same core keeps1,208widgets and passes all close/
  resize checks in44.96s, with2reflows/switch and switch medians78.30/77.70/
  78.79ms. Only2/189 switches exceed100ms; largest loop gap114.05ms, GC3.61ms.
  Native recheck `toad-source-ready-native-nav` completes83actions/singleton
  channel IDs; loop max133.73ms, GC87.48ms. This is a correctness-preserving
  elimination of duplicate work, not a claim the full frame pipeline is fixed.
- Full current-core Pytest run `toad-workspace-l0a-full`: **166 passed +82
  subtests,23 failed in598.55s**, peak421.9MiB, zero swap. Do not label it green.
  The fixed earlier subset of5 smoke cases is not a full-suite substitute.
  After the run, right-panel-on-reveal fixtures were corrected without relaxing
  visible assertions (message categories, in/out filters, busy relationship
  spinner, recovery dual-root and channel-source update); targeted6passed and
  channel-views passed separately. The permanent TL0 guard now passes using the
  distinct nominal `SessionSurfaceLifetime` name instead of reintroducing the
  deleted `SessionPresentation` class. The blank-shell guard now checks the
  actual `self.shell` access, not the new typed `app.settings.shell` declaration.
  A complete suite repeat is still pending after those changes.
- Matched baseline worktree `/tmp/opencode/toad-l0a-baseline-df0a` is detached at
  unmodified main #107 `df0a758` with the **same core2bfbdb2 and Textual source**.
  Its pilots independently reproduce failures in `comms` (unchanged10s saved
  transcript condition), `session_sort` (removed core Publisher.publish),
  `default_route_private_user` (removed scheduler), `goal_objective_edit`,
  `channel_history_reader` (new private-bus file ownership),
  `current_delivery_owner`, `channel_retirement` and `thread_unread_start`.
  `channel_views` passes on that baseline, so its initial one-pause publication
  assumption was our integration-specific failure; a bounded wait for the same
  canonical update now passes. Baseline source files and other agents' worktrees
  were not edited. Findings reported to the owning merged #107 PR.
- The current full-suite non-green state is **not** attributed wholesale to #107:
  this PR's lazy right panel initially made hidden widget queries fail; they now
  reveal the panel and await its real mount before testing paint and filters.
  Focused visual/category/filter/spinner/recovery contracts pass. Other core-
  related failures are retained with exact baseline reproduction; their tests
  are neither skipped nor assigned a longer deadline.
- Two app-env pilots initially failed at import-time because the new isolated
  core-only environment lacked the pytest test dependency. The isolated env now
  has pytest9.1.1 with its ordinary package requirements; this does not alter
  the pinned production dependencies or change a test assertion. Their
  subsequent failures are included in the matched baseline classification.

This revision remains draft: native data-layout/GC tails, exact stable-switch
budget, full suite failures and unbounded agent-backed presentations are still
real acceptance gaps. Do not merge on the strength of the blank fixture alone.

## Loaded agent-backed scaling: outstanding tail owner

With the same `2bfbdb2` core, Textual editor branch and source inventory, the
synthetic loaded fixture deliberately keeps a Conversation attached to each
agent-backed tab. Those message targets receive ACP updates and own protocol/
permission handling; evicting them as if they were blank would discard or
misdirect operations. These tests are an explicit counterexample to treating
the blank-session improvement as a general bound:

- Strict **16-tab loaded** visit/resize/close run:17 Conversations/editors,
  2,367 widgets after visits; warm medians~50–53ms. One observed warm switch
  119.15ms with69.04ms GC and121.30ms loop gap.
- Strict **32-tab loaded** run:33 Conversations/editors,4,479 widgets after
  visits and~0.71–0.76m tracked objects. Warm median~60–61ms. A collection
  lasted156.64ms and produced a162.83ms loop gap during forward visits,
  despite switch-to-await maximum84.36ms: frame/loop stalls and coroutine
  completion are different measures. Scope peak398.6MiB, zero swap.
- The **64-tab loaded full run** reached its unchanged240s diagnostic cap
  after creation (8,704 widgets) and two63-visit phases; it has no completed
  full acceptance receipt. A follow-up explicitly marked `--phase-only` and
  limited to reverse-first/forward-second completed those phases in234.24s.
  Its first/warm medians74.38/77.58ms; maxima371.83/321.99ms, with GC
  285.46/242.09ms and loop gaps375.91/325.33ms. 65 Conversations/editors,
  8,703widgets and~1.19–1.24m tracked objects persisted. This result does NOT
  include resize, same-mode, close or third-visit acceptance. A distinct
  incomplete `.phases.json` receipt is written at each completed phase for a
  bounded run; it cannot be misreported as a full pass.

Conclusion: the quadratic tab-strip duplication is removed and blank sessions
have one rich view, but **executing-agent presentation is still proportional to
the number of mounted modes and retains an expensive collector graph**. Source
handling cannot be replaced with an unbounded queue of raw UI messages or a
widget teardown that calls `Agent.stop`. A long-lived nominal session/source
controller must receive actual ACP/queue/permission updates independently of
the rich optional surface, with typed source-backed restoration, editor intent,
and a bounded global presentation admission policy. The T2/T5/viewport owners
are being integrated on main; #116 has requested assignment of that Agent
target boundary through the parent dispatch instead of inventing a parallel
reducer. This PR remains draft until that actual ownership change and fresh
loaded worst-case/native tests are complete.

No installed runtime, live data, user preview or other agent worktree was changed.

## Viewport follow-tail and recent-window checkpoint

On the branch pinned to core `853630552df22e16106a016ab24dfa70f5538ae5`
and Textual `d9def32ff25b56304b3e03ad4bf59d750b4d238b`, a mounted
48-record source reproduced two separate regressions. Repeated reverse/forward
scrolling rebuilt a recently viewed non-tail body three times with the old
eight-body window. An End key press after its tail was retired submitted a
frame with follow-tail enabled and the tail visible but its source body not
ready. The fail-before frame tuple was `(True, True, False, 834, 834)` for
`(follows_tail, tail_visible, tail_body_ready, scroll_y, max_scroll_y)`.

The active document warm set is now 24 bodies and an application-owned pool
retains at most three recently visited windows. Displaced windows request
reconciliation, retiring their warm bodies; this is a global recent-window
budget, not an unbounded per-tab cache. Every current-screen compositor refresh
checks **visible** source-body readiness before painting. Repeated Page Down/End
now reaches the painted source tail with at most one rebuild of the sampled
recent tail/non-tail bodies. A two-window test budget verifies the oldest body
retires across four tabs and a recent tab is ready on return.

Seven serial focused pilots pass: rapid-scroll/End, recent-tab retirement,
viewport body lifetime, history scroll frames, 2,000-record anchor geometry,
off-tail checkpoint retirement and shared blank-editor transfer. The existing
240-second loaded-64 run and its phase-only worst GC are not displaced by
these focused checks. The current native terminal fixture, after updating its
diagnostic observer for the core's typed transcript/category/target APIs,
completes **83 actions / 10 tabs / eight sidebars resizes** with four channel
identities each singleton across modes. Capture
`toad-round2-viewport-native-nav-5` has scope peak 615.2 MiB, zero swap;
loop gap median/p95/max 15.02/53.54/129.95 ms and GC maximum 119.33 ms
(UI-thread maximum 109.54 ms). Those tails are still above the user's target;
the fixture exercises native navigation and scrolling, while the held-source
End frame is checked by the focused mounted pilot. A full integrated test
result and bounded executing-agent presentation remain outstanding.

## Current-main T4 integration and installed checkpoint

This next checkpoint merges Toad main `b4bdae1` into #116 at `4a602da` and
uses its exact core `4510dddf737da3d445ba20d90c79f3dcb3f08b27` and
Textual `c9743801c98dc570f82f82e25915ecce89800f4b` (which includes
merged Textual #8). No shared runtime or user display was touched. The
isolated `toad-workspace-round3-20260928` wheel includes the locked project
and persistent renderer extra; pytest's canonical collector runs that wheel,
not a source-path override. Its native Pi package was verified against the
core-owned tree commitment before test use.

- Integration exposed a real CSS/measurement regression: T4's nominal
  `ConversationBlock` initially extended Textual `Widget`, preceding
  `PreparedConversationMarkdown` in leaf MRO. In a 48-record mounted source,
  only the first body had a positive layout height, the remaining 47 were
  zero-height/unmeasured, `max_scroll_y` was 71, and bodies could not retire.
  The contract is now a nominal non-DOM mixin, leaving each concrete widget
  as the single native CSS/layout owner. Inactive history anchors stop
  protecting a displaced window's warm body. Mounted rapid-scroll, recent-tab
  and 32-body retirement tests pass after both fixes. Main independently
  incorporated the same CSS fix in #137.
- Main's `AgentReady` accidentally omitted `Message.__init__()`: posting the
  ready notification failed with missing Textual message state. This branch
  restored its base constructor; `shared_channels_pilot` passes. Main
  independently incorporated that fix in #134. The agent-side T4 request for
  eager shell startup remains omitted to preserve the workspace guard: blank
  tabs do not start unused shells. The installed architecture/lifetime subset
  passed **10/10** (including the held-source End and recent-window pilots).
- Strict **64 blank tabs / 64 fixed source threads**: three visit phases,
  resize, same-mode and close checks completed in **42.58 s**, retaining
  **1,179 widgets, two Conversations/editors, one header/Footer/Channels**, and
  65 labels and close buttons. Phase switch medians 76.00/76.23/76.30 ms;
  loop-gap maxima 100.61/94.25/109.93 ms, GC maximum 5.93 ms. A separate
  fully loaded 10-tab run completed in 18.10 s but still retained **11
  Conversations/editors and 1,527 widgets**, demonstrating that loaded views
  remain proportional to modes. Its switch medians were 42.47/44.92/30.59 ms.
  Both receipts use the same current installed wheel and ordinary GC.
- Native owned display `:198`: `toad-round3-native-nav-2` completed 83
  actions/10 tabs/eight sidebar resizes with four singleton channel identities.
  Loop gap max **166.54 ms**, GC max **133.09 ms**; scope peak 608.4 MiB,
  zero swap. Fixed category-fixture selection in the observer input route;
  `toad-round3-native-filters-20260928` completed **180 actions**, seven
  categories, restored drafts across 10 modes and **130/130 native key
  acknowledgments**. Key median/p95/max 29.38/52.25/63.06 ms; loop gap max
  **225.01 ms**, GC max **197.64 ms**; scope peak 642.8 MiB, zero swap.
  Functional visibility/input passes, but the worst-case stall target does not.
- The complete canonical installed-wheel run was **257 passed, 13 subtests
  passed, 49 failed in 1,636.49 s**. It is explicitly **not green**. Failures
  include deprecated typed fixture imports, strict nominal block admission in
  older direct-mount pilots, hidden-on-reveal right-panel assumptions, markdown
  parser root assumptions on history/file preview screens, and native/goal
  readiness cases. The full failure output is in the runner's captured pytest
  receipt under `toad-round3-canonical-suite-20260928`; tests were neither
  skipped nor given longer per-pilot deadlines. The performance probe's one
  installed-wheel provenance failure was corrected after that run; its normal
  10-tab and strict-64 executions above subsequently completed. This is not
  a claim that the other 48 failures are resolved.

Since this receipt, main has merged #131, which provides public
`Agent.attach_surface`/`detach_surface` and agent-owned permission custody, as
well as #137/#134. These contracts now permit #116 to implement bounded
agent-backed presentation without parallel ACP reducers or operational-message
replay. They have **not yet** been integrated or measured on this branch.
