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

No installed runtime, live data, user preview or other agent worktree was changed.
