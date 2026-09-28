# Workspace integration and global surface boundary

PR12651c901c remains unchanged and ready in its own tree. This separate persistent
worktree integrates published1161cb7c74/126 with Toadmainc3f7b63 and current core.
It preserves the original editor-state feature dependency Textual8d9def32f;
Textualmain16ede lacks TextAreaState, as an actual installed import failure showed.
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
