# Workspace integration and global surface boundary

PR12651c901c remains unchanged and ready in its own tree. This separate persistent
worktree integrates published1161cb7c74/126 with Toadmainc3f7b63 and current core.
Textual8 is merged at main c9743801; its reviewed receipt reports 307 focused
and 3515 full framework tests. The merged framework owns TextAreaState.
No compatibility layer or copied editor-state mechanism was introduced.

## Agreed file ownership

Carver owns acp/agent.py, acp/agent_process.py, agent_presentation.py and the
Conversation operational permission/attachment/queue regions. His proposed
Agent-owned PermissionController is confirmed: pending typed requests/futures,
resolve/cancel and optional presentation subscription. Surface detach must leave
requests operational; Agent.stop/session replacement cancels. QueueAttachment
remains the sole queue authority. Mounted target.app cannot remain the validation
context authority after detach; stable operational context belongs to Carver.

Sol owns session_presentation.py, workspace_chrome.py and MainScreen/App surface
admission/activation/retirement callers. Existing116 OpenCode owner retains its
active workspace/source-controller claim and dirty125 integration. Consume only
published checkpoints; do not copy the predecessor's uncommitted merge.
Agreement recorded on127 comment5880410294 and116 comment5880382597.

## Implemented integration/deletion closure

- Bind SessionThreadSidebar directly to current MainScreen.coordination_root;
  retired _coordination_root storage is not restored.
- Migrate blank editor visibility to declaration-derived all_categories(), with
  nominal category classes as typed state; no ALL_CATEGORIES roster restored.
- Preserve current typed ScreenCommsConsumer/CoordinationChangedUpdate dispatch,
  shared ViewportPresentation, current log viewer, root and renderer contracts.
- Retire the departing surface under App's existing mode-switch lock before
  preparing the selected surface. Delete detached retirement workers which can
  race a return to their own mode or permit multiple surfaces pending retirement.
- Consume Carver142319c production bootstrap deletion: no MutationStore or four
  manual schema installers in the real native fixture. Core27876855582 is explicit.

## Actual acceptance so far

Noneditable installed currentmainc3f7b63 + core27746b729cf + Textual8d9def32f +
verified native5fdef596 passed all three strict visit phases at4/16/32/64 tabs.
Same real ACP process/read-loop/native owner/session remained operational while
inactive; held+queued inputs completed exactly twice per cohort, native answers
painted on return, original editor/document/history/draft/undo survived.
One fixed native owner/ACP attachment, eight loopback-only HTTP model requests;
no paid model calls or mocked transport/queue/editor/renderer methods.
64 sample:262.6MiB UI RSS,5816 tasks, zero rich panels,79.87ms settled headless
median,2/189 >100ms. This is not64 executing agents or native-terminal latency.
Core278 production-bootstrap rerun passed the same installed path after the
serialized retirement change, exit0: all four cohorts, eight native calls and
painted answers.64:264.3MiB UI,5816 tasks,81.95ms settled median,6/189 >100ms.
Receipts: current-bootstrap-retention.json/current-native-production-bootstrap.log.

Strict manifest rejection of native905 and missing TextAreaState/import failures
remain recorded rather than hidden. Focused settings guard passes and affected
undefined-name/static closure passes. No CI wait or live/predecessor mutations.

## Concrete incomplete global bound

Serialized admission alone is not the complete resource bound. Existing retained
lifetime still retains rich Conversation per logical agent-backed mode. Carver's
permission/source boundary must integrate with116's long-lived typed session
controller: operational Agent/queue/tool/permission facts survive without an
optional rich view, the selected view restores actual editor state and observes
existing source facts, and inactive rich trees are retired. No raw event buffering,
second reducer, Agent.stop on surface retirement, default-off path or claim of
full116 completion. Final matched loaded/native resource acceptance remains required.

## Continuing selected-only implementation checkpoint

Merged Textual8 mainc9743801c98dc570f82f82e25915ecce89800f4b now replaces the
feature pin. Framework dependency is resolved, with exact focused/full evidence
reported in126 comment5880516638; ready12651c901c is unchanged.129 now integrates
Toad128b472e487 and core280487ebb9ec4468a70a92fc172dd5f2f50950a3c87.

Actual new paired installed run caught a real native return-paint failure: both
NATIVE_RESPONSE_1/2 reached ACP, but compositor did not paint the second answer.
Failure receipts/regions retained; the assertion is not weakened. The response
block is below the visible window while saved TranscriptHistory remains the old
snapshot. Carver's source-backed restore(binding) on new presentation is the
required contract; no raw UI-message replay or duplicate transcript store added.

Implemented in source (not yet installed accepted against unpublished contract):
- OperationalSessionPresentation replaces retained-per-mode custody in place.
  Its Screen composes a lightweight SessionSurfaceSlot. Prepare constructs the
  selected rich view; retire captures SessionViewState, retains the actual Agent,
  calls its explicit detach_surface before remove, preserving operational custody.
- SessionViewState capture/restore now owns editor/history/selection/scroll/filter
  semantics shared with blank custody. No parallel editor-state carrier or alias.
- MainScreen hydration delegates lifetime preparation under the owner's lock;
  it no longer independently builds a second Conversation.
- Blank operational promotion retires the old surface before another is admitted.
  Blank parking Screen/mode deleted: only state survives nonblank selection.
- Logical close stops the retained operational attachment; optional UI retirement
  is distinct. Caller hooks migrated without resurrecting compatibility names.
- Native acceptance now reads queue from Agent.queue_attachment while detached,
  reacquires restored editor on return, checks same document/history/session/process,
  and asserts one rich Conversation across all registered mode stacks at each cohort.
  Actual native rendered-answer assertion remains required.

Carver's unpublished AgentController/PermissionController/Agent attach/detach and
source restore were inspected read-only, not copied. Publish/consume that coherent
contract before claiming global installed acceptance. Operational shell/terminal
custody and already-revealed optional sidebar state/global retirement still need
closure; current source is not full116 readiness. The new source-bound gate remains
strict; no mocks, no phase filtering, no default-off path or paid calls.

## Installed selected-view acceptance after source integration

Consumed published Carver6c689ba, preserving actual AgentController ownership.
Corrected ConversationBlock into a nominal concrete-behavior mixin so native
widget CSS inheritance remains authoritative; removed obsolete body_windows
callers and released retired viewport membership/subscriptions before unmount.
The existing DirectoryWatcher now rebinds across optional views and remains
operational with the logical session; only logical close stops its source.

Actual installed core280/Textualc974/native5f path completed all four cohorts
(4/16/32/64), eight loopback model calls, original document/history/undo identity,
unchanged ACP/native owner/session and painted returned answers. Each cohort
asserted exactly one globally mounted rich Conversation. Receipt:
workspace-bound/global-bound-retention.json; log global-bound-watch-fixed.log.
At64: 162.54 MiB UI RSS, 996 tasks, zero constructed sidebar panels,
235.69 ms settled headless switch median (189/189 above100 ms). This is one
operational native owner across64 logical tabs, not64 executing agents.
The resource bound passes this case; switching cost remains a concrete regression.
Three installed turn-navigation/guard tests passed after CSS correction.
Failures before correction are retained, including actual compositor failure,
obsolete viewport membership and path-observer teardown timeout.

Remaining full116 closure: operational shell/terminal source custody, previously
revealed sidebar state/retirement, and final paired acceptance rebased onto132
with core4510. Ready126 remains unchanged. No full116 readiness claim.

## Final PR132 paired acceptance

Current main132 b4bdae1 is integrated preserving116/126/source ancestry; pins
core4510dddf737da3d445ba20d90c79f3dcb3f08b27 and Textualc9743801.
Noneditable installed source files were compared with the branch; current merged
source is installed. The actual ACP/native retention run exited0, all4/16/32/64
cohorts completed,8calls, rendered answers and actual document/history/undo
preserved,1globally admitted Conversation throughout. At64:167.11MiB UI RSS,
996tasks,229.08ms settled switch median; no revealed sidebar panels in this case.
Focused installed turn-navigation/guard tests:3passed2.94s. Receipts:
main132-retention.json/main132-native.log/main132-navigation.log.
Shell/terminal and revealed-sidebar closure remain explicitly assigned to Sol129;
current result is not a claim that those operational paths are accepted.

## Shell source closure

Shell now owns actual PTY/process/reader and existing ANSI TerminalState models;
nominal ShellOutput leaves present command/terminal state without retaining old
Conversation/Terminal graphs. Retire clears optional view bindings; prepare paints
original state. Command bytes are never replayed. Existing Terminal.write delegates
projection to project_state; no second decoder/model. Legacy Shell.terminal and
strong Conversation source authority are removed. CWD source state survives detach;
logical close uses shared process grace and retires owned PTY/task.

Actual installed blank_presentation_pilot now sends sleep1/printf through realPTY,
checks completion with no view present, same shell process/task, restores same ANSI
state into returned terminal with compositor-painted marker, preserves drafts and
actual undo/selection/document, checks logical close reader/process retirement.
Final receipt shell-width-retention.log exit0. 47terminal/navigation contract tests
passed. The installed shell checkpoint also passed complete actualACP4/16/32/64
retention with8loopback calls/painted answers/original editor identity.

A separate concrete gap remains in ACP terminal RPCs: mounted Conversation still
owns Create/Get/Wait/Kill/Release handling. Sol owns TerminalTool operational source
extraction and typed terminal controller; Carver requested exact Agent RPC caller
migration independently on131 comment5881128131. Noether boundary is129 comment
5881034627: optional sidebar only, MainScreen hooks remain Sol-owned.
Profiling switch4 found viewer_snapshot and widget compose/CSS as major costs;
profiling receipts are diagnostic,4cohort timings include profiler overhead.

## ACP terminal operational extraction

The concrete terminal RPC gap is implemented in129: TerminalExecution owns the
existing Command/ToolState, actual PTY/task, original ANSI model and protocol output.
TerminalController owns terminal IDs and executions. TerminalTool is only a weak
optional view projection; source remains alive when rich UI retires. Agent's
terminal create/output/wait/kill/release callbacks address that source directly.
Delete Conversation's UI terminal reducers, the five obsolete ACP terminal message
classes, widget-owned process/output methods and unused Agent terminal counter.
All callers/imports migrate without aliases. Shared rendering moves to nominal
TerminalStateProjection; ShellOperationalSource owns shared operational lifecycle.
Session presentation separates original editor state from OperationalSessionSources.
Terminal resize behavior is a polymorphic capability: ACP view resizing updates
its own execution and does not spawn an unrelated conversational shell.

Installed actual native attachment plus production JSON-RPC callback dispatcher
and realPTY acceptance passed: active terminal finishes while detached; another
terminal is created/waited/read while absent; unchanged realACP/native owner and
session remain alive; original ANSI state paints on return; actual running command
kill, released-ID rejection, task/process cleanup pass. This dispatches callbacks
through the real server entry; it does not claim Pi spontaneously issued those
terminal callbacks over its pipe. Receipt acp-terminal-native-final.log.47focused
ANSI/navigation contracts passed3.05s. No provider calls in terminal acceptance.

Carver's proposed RPC slice had no response while source work proceeded; Sol
completed that exact terminal-only caller region instead of leaving an unowned
handoff. Other Agent lifecycle/queue/permission regions remain untouched. Final
paired4/16/32/64 resource/ACP/editor rerun and switch-caller profile are running.
