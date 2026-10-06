# Current MCP/typed consumer family: coherent source checkpoint

Base Toad470 b67020085c72a7aa6a048feaaf4d814fc6a926d7. Draft472 is source-qualified only. No application imports, test collection, test execution, installed package, SDK/native/provider/input or holder operation occurred. Recorder473 is preserved separately and adopted by Heis. Frozen468, original06, l0a, runtime_fixture, production and pins are unchanged.

## Facts and original owners

| Fact / lifetime | Existing owner used by all related controls |
| --- | --- |
| Thread declaration / ACP attachment | SessionLifecycle.declare_thread / bind_owned, ThreadManagement.claim_thread |
| Admission / busy / managed identity | AgentActivity.begin_turn, RegistryOwner.turn_lease, TurnState, Agent.current_turn |
| Phase / progress | AcpEventConsumer.on_compaction -> TurnRunner.observe_compaction -> CompactionObservation; declared CompactionSourceProgress |
| Terminal / stale release / waiter retirement | TurnRunner.acquire_turn/settle_turn/finish_turn and AgentActivity.finish_turn exact lease CAS |
| Published turn cut | TurnTranscriptUpdate -> original ACP SDK model -> TurnChangedUpdate -> ManagedTurnBinding |
| Goal clear | GoalScheduler.sync_goal_execution -> existing goal_changed observation; no authored goal payload |
| Notification ingress | Agent.server.call -> ordered SessionNotificationOwner.receive and SDK validation |
| Permission JSON / pending request / answer | Server.call -> PermissionController; original RequestPermissionResponse is encoded by that boundary |
| Rich surface detach / eviction / remount | Logical MainScreen.presentation.retire / evict / prepare, OperationalSessionSources, original PermissionPresentation |
| Child / blocking operation cleanup | ParentedProcess and Coordination.run_worker (joined cancellation before custody exits) |

## Concrete deletions and complete three-file migration

`mcp_observation_fixture` removes fabricated start/settle records and deleted private Agent fields. The shared `turn_source` uses the original metadata owner, real current-process thread declaration, bound ACP session, actual leases and cleanup enlisted before worker delivery. It does not enroll saved history, record native input or manufacture a native witness. Its two inherited caller selectors are cleared only for this isolated metadata owner's lifetime and restored after cleanup; they must not name a participant from the public registry during original same-process stop.

Boundary controls retain foreign-session, retired-receipt, malformed-version, duplicate-receipt, stale lease CAS, earlier finished-cut, current terminal and late-receipt checks. Earlier finished cuts come from an acquired and settled original lease. The authored MCP receipt is test data, explicitly not a native MCP grant. Native observation remains the external producer's separate callback path.

`typed_comms_command_pilot` deletes the embedded producer and obsolete `AcpEventConsumer.settled`, raw AgentDefinition, view.activity, exact busy_count and private turn fields. Its own declared producer consumes the shared original resource, publishes typed phase observations through AcpEventConsumer and releases the exact lease. The stale terminal cut and real goal-clear publication are delivered through the SDK JSON pipe. Original ParentedProcess owns the child outcome; Coordination joins pipe communication before process/stream custody exits. Output uses an explicit persistent `--output` path. This is authored protocol/phase acceptance, not native compaction execution.

`native_permission_ui` preserves external `open_observer(case, artifact_dir)`, `session_update`, `request_permission` and `disconnected` shapes. It borrows the logical session's current conversation instead of storing a removed widget. SDK JSON ingress owns both permission argument decoding and response encoding. The mounted offered options and preview still must paint before the explicitly simulated answer. Original presentation retirement/eviction/remount retains the original pending permission; no manually constructed replacement Conversation remains. Disconnect retains cancellation semantics. Every permission task is joined on failure, and observer setup/boundary failures now pass through Agent.stop cleanup.

Relevant catalog relations: BOUND-2 (use the existing SDK/turn/surface owners), BOUND-5 (remove embedded producer source), IMPL-13 (original child/cancellation mechanism), AGENT-2 (migrate the producer and all three consumers together).

## Source checks and precise remaining boundary

BEFORE-OWNER-CONSUMERS.json retains the original caller/declaration evidence. AFTER-OWNER-CONSUMERS.json records the original `audit.findings.Package` full roots, omissions, source compiler results, exact three-file scope, actual declared Core pin and consumed declaration relation. The initial evidence scope assertion included an already tracked documentation file; the corrected source-only comparison and that negative are recorded. These checks execute no application module.

Core `tests/test_mcp_acceptance.py` remains a genuine external selector: `AC_MCP_TOAD_ADAPTER` loads a module exposing `open_observer`. That Core opt-in native qualifier still imports and consumes deleted TurnStartedUpdate/TurnSettledUpdate. It is outside this three-file write grant and cannot currently qualify the repaired observer. Arbitrary externally supplied adapter modules cannot be closed by the static caller census. No aliases or alternate adapter have been introduced to hide this limit.

Future affected acceptance, UNRUN and requiring a separate scope: first the authored producer -> mounted typed turn/phase/stale-cut/goal-clear path; then the original real native MCP harness after its declaring owner migrates that current turn consumer, including actual permission paint, offered-answer selection, retained-surface permission rebind and disconnect cleanup. No existing native/UI/provider qualification is borrowed. Heis remains the sole continuous-workflow/recorder/runtime integrator.
