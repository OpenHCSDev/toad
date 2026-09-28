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
