# TC2 execution receipt

**Status: ready for integration review; all assigned TC2 consumer/deletion work and the actual paired installed journeys passed.**

**1,163 production lines deleted; 738 added, net 425 removed** against integrated Toad main `cd791811` (#209), across 45 production files. This includes the 504-line `acp/protocol.py` deletion. Initial base was `7e1133a2`; normal integrations preserve #207 receipt/history work and #209 manual/autonomous compaction progressive bodies. Final integration of `cd791811` applied without conflicts, including Conversation callbacks and the native runner; no callback was manually resolved. Per owner instruction, disjoint source integration does not repeat the completed broad journeys; #209's own receipts remain in the coherent tree. No compatibility readers or alternate codecs remain for TC2.

Owner: TC2 worker. Draft [Toad #208](https://github.com/OpenHCSDev/toad/pull/208). Persistent worktree: `/home/ts/wt/toad-cleanup-tc2-sdk-20260929`. Working code checkpoint `348080fe` was pushed before current-main integration.

## Required relation and consumer closure

BOUND-1, BOUND-7, TIME-8: official `agent-client-protocol==0.12.1` is the sole ACP specification schema. The existing JSON-RPC transport decodes declared request arguments and response results with SDK/Pydantic models once, serializes models at the existing envelope boundary, and retains the original transport. MCP and prompt unions are derived from SDK field declarations. No second ACP schema, schema union roster, codec subclass, or validated-model-to-raw-dict cast exists.

The complete update relation is wire request -> `SessionNotificationOwner` -> existing renderer validation task -> accepted/rejected result family -> SDK notification -> declared `SessionUpdateEffect` -> operational owners -> UI messages/presentation. Core extension metadata still goes through its existing `decode_updates` owner; Core snapshots and goal RPC payloads are outside the ACP specification, belong to C3, and are not relabelled as ACP records. Unsupported, unadvertised SDK update capabilities are rejected visibly rather than silently ignored.

SDK 0.12.1 implements the external schema's deliberate lenient optional-field/list deserialization even when Pydantic strict mode is requested. TC2 honors that external contract. A complete plan replacement additionally checks whether the SDK dropped malformed entries; it rejects the replacement instead of false-clearing the retained valid plan. There is no second PlanEntry decoder or local copy of the schema. Actual stdio missing-priority, wrong-status and wrong-content cases preserve the prior plan and paint rejection notes.

IMPL-1, MEMB-3: protocol-spelled `StopReason` and `ToolCallStatus` members own completion, notes, headers, activity and boundary behavior. Tool status is chosen once at tool admission, carried with the original SDK ToolCall capture, and consumed by Conversation, tool headers, expansion settings and history. `SessionToolCalls` remains the single operational call assembly owner; no additional status store was introduced. Dead Conversation diff/tool emitters and the exact local Mode NamedTuple mirror were deleted. Mode advertisements and all UI consumers retain the original SDK SessionMode instances, verified by identity across initialization and mode changes.

BOUND-1, TIME-8: `AgentDefinition` decodes agent TOML and CLI-generated definitions once through existing FieldCodec. ACP uses a public immutable definition, and all definition consumers use attributes. Existing durable session metadata retains its external `type` key through a scalar TextRepresentation of the declared `AgentKind`; there is no old-format reader or renamed-key fallback. Kind declarations own grouping and presentation, so adding a kind changes its one declaration. Catalog validation also corrected Goose's existing singular `action` TOML typo to the actual `actions` contract.

MEMB-3: accepted image/Markdown suffixes, media types, image capability and preview behavior live in `FileKind` declarations. Prompt attachments, resource MIME projection and project preview consume that same family. Adding an accepted kind requires its declaration only.

File, permission and terminal client requests accept SDK types and return SDK responses. The real stdio journey exposed the old negative process exit-code bug; `ToolState.capture` owns OS return-code decoding, and both output/wait project the same signal or exit status without a mirror. The UI's terminal lifecycle continues to use the original execution owner.

## Coordination and crossings

- Schrodinger owns #207/#210 receipt/history/source lifetime. No competing cache/performance implementation here.
- Heisenberg owns #202 workspace/session presentation. His `465962da` saved-history capability was integrated as `4d56a187` to prevent ordinary SDK peers being sent through comms transcript paging. Actual A/B/A SDK stdio acceptance passes with it.
- Arendt owns #416/#209 compaction accounting/progressive presentation. TC2 preserves his extension contract and does not hold its activation.
- Conversation changes here are ACP stop/tool consumers and typed definition access. Activity/status/cancel integration remains with the parent/T4 owner.

The historical `toad-acp-sdk-migration.md` named by the zip was not found in the repository/plans/archive searches. The current TC2 zip, actual SDK declarations, current entrypoints and physical journeys supplied the verified contract. No behavior was inferred from the missing document.

## Installed acceptance

Tests execute a noneditable installed wheel from this WT's `.venv`, not source imports or a patched UI/protocol/state implementation. Providers are official SDK local stdio peers or the existing bounded localhost response fixture. Native journals, subprocesses, owners, ACP, renderer workers, UI and physical clicks remain real. No paid provider call or user-history replay occurred.

| Actual journey | Evidence and result |
|---|---|
| SDK initialize/new, plan status/sidebar/completion/reset, malformed required entries, detached plan and A/B/A retained agent/process/editor | `plan_status_installed_pilot.py`: exit 0 again on current accounting pair; `evidence/tc2-sdk/logs/plan-accounting.txt` |
| Native Read/Edit/Bash, typed tool output, copy/collapse/reopen and paint | `native_tool_output_pilot.py`: exit 0; `native-tool2.log` |
| Native model/thinking picker, high selection, ACP reconnect, retained saved answer/draft/document/undo | `agent_configuration_native_installed_pilot.py`: exit 0; `native-config-settled.log` |
| Production fork, physical immediate opening before worker socket, inherited history, first input and exactly one answer in same logical tab | `first_fork_native_installed_pilot.py`: exit 0; `native-fork2.log` |
| SDK file read/write, physical diff permission, terminal env/output/wait/kill/release, signal status, tool progression and painted answer | `acp_specification_installed_pilot.py`: exit 0 on current accounting pair, including original SDK mode identity and mode changes; `sdk-rpc-modes.log` |
| Complete current-pair native entrypoint: input, queue, native history, saved checkpoint, reconnect, DM, channel receipt feedback, stopped-owner reopening | `l0a_native_installed_pilot.py`: exit 0; `continuous-accounting-selected.txt` |
| Focused family/deletion/format/session/configuration contracts | 5 passed, 0.92s on the new accounting pair |

Earlier failing attempts are retained honestly: the SDK A/B/A journey exposed the missing presentation capability; the native tool fixture addressed the obsolete screen conversation owner; the fork fixture used the obsolete combined name/task field; the final configuration click preceded painted menu layout. Their fixes use current owners and actual layout admission; no receipt/retention/input assertion was weakened.

Initial accepted installed pair: Core `d6a2ac55`, Textual `412b5a2b`, native `776dc368`. Current own-WT installed wheel and stdio fixtures pass on Core `ab3397a6` (#416/#423), integrated Toad #207, Textual `412b5a2b`, SDK 0.12.1; native fixture target `7817b54e`. Combined new-pair native saved-history/queue/DM/channel/restart acceptance passed: `l0a_native_installed_pilot.py` exited 0 on Core ab3397a6/native7817, with queue input mapping, saved checkpoint/paint, cold ACP attachment without replay, direct reply, channel busy/idle and Checked — no response, stopped-owner reopening and zero additional requests during idle. The first run selected the old DM with a workspace-wide query; the corrected driver waits for the selected logical session and scopes both DM/channel queries to it, retaining target/kind and notification assertions. Both runs are preserved under `evidence/tc2-sdk/logs/continuous-accounting*.txt`. All fixture owners were retired; the serial slot was handed directly to #202, then the compaction speed worker. No default/global installation has been changed by this worker; parent owns paired activation.

## Guards and measurement

`tests/guards/test_acp_specification_ownership.py` enforces the deleted schema, typed consumer closure/private-definition prohibition, SDK spelling equality and FieldCodec external format. Existing focused session/configuration tests retain their lifecycle assertions. The obsolete mocked boundary pilot was deleted; installed stdio/native journeys provide the behavior evidence.

Canonical debt ratchet at pushed `53b879d0` against initial base reports **zero positive measures and 95 fewer string-keyed subscripts**. Final accounting/modes checkpoint `270cb160` against current main `533c7f6c` reports zero positive measures and 94 fewer string-keyed subscripts. Both machine summaries and command logs are preserved under `evidence/tc2-sdk`. This is scoped structural evidence, not a claim of a complete NRA proof or whole-application readiness.

## Changed production files

Counts below are exact `git diff --numstat cd791811 HEAD -- src/toad` for the current working checkpoint. Removed lines are source lines, not a semantic-debt score.

| File | Added | Deleted |
|---|---:|---:|
| `src/toad/acp/agent.py` | 10 | 10 |
| `src/toad/acp/agent_configuration.py` | 5 | 7 |
| `src/toad/acp/agent_controller.py` | 6 | 6 |
| `src/toad/acp/agent_session.py` | 28 | 50 |
| `src/toad/acp/api.py` | 13 | 13 |
| `src/toad/acp/client_files.py` | 5 | 3 |
| `src/toad/acp/context_measurement.py` | 1 | 5 |
| `src/toad/acp/messages.py` | 10 | 9 |
| `src/toad/acp/notification_items.py` | 9 | 13 |
| `src/toad/acp/permission_controller.py` | 5 | 5 |
| `src/toad/acp/prompt.py` | 6 | 5 |
| `src/toad/acp/protocol.py` | 0 | 504 |
| `src/toad/acp/sdk_boundary.py` | 8 | 20 |
| `src/toad/acp/session_updates.py` | 79 | 77 |
| `src/toad/acp/status.py` | 97 | 0 |
| `src/toad/acp/terminal_owner.py` | 9 | 12 |
| `src/toad/acp/tool_calls.py` | 19 | 20 |
| `src/toad/agent.py` | 2 | 1 |
| `src/toad/agent_presentation.py` | 14 | 0 |
| `src/toad/agent_schema.py` | 79 | 58 |
| `src/toad/agents.py` | 8 | 8 |
| `src/toad/app.py` | 2 | 2 |
| `src/toad/cli.py` | 8 | 8 |
| `src/toad/data/agents/goose.ai.toml` | 1 | 1 |
| `src/toad/db.py` | 2 | 1 |
| `src/toad/file_kind.py` | 60 | 0 |
| `src/toad/jsonrpc.py` | 39 | 27 |
| `src/toad/permission_presentation.py` | 6 | 6 |
| `src/toad/plan.py` | 2 | 2 |
| `src/toad/prompt/resource.py` | 2 | 0 |
| `src/toad/render_tasks.py` | 27 | 13 |
| `src/toad/screens/agent_modal.py` | 15 | 15 |
| `src/toad/screens/main.py` | 3 | 3 |
| `src/toad/screens/store.py` | 28 | 48 |
| `src/toad/session_admission.py` | 1 | 1 |
| `src/toad/session_presentation.py` | 1 | 1 |
| `src/toad/setting_choices.py` | 8 | 8 |
| `src/toad/slash_command.py` | 2 | 3 |
| `src/toad/terminal_execution.py` | 15 | 5 |
| `src/toad/tool_output.py` | 40 | 22 |
| `src/toad/widgets/conversation.py` | 25 | 111 |
| `src/toad/widgets/project_panel.py` | 2 | 8 |
| `src/toad/widgets/prompt.py` | 5 | 5 |
| `src/toad/widgets/tool_call.py` | 15 | 37 |
| `src/toad/widgets/transcript_history.py` | 16 | 10 |

Other changed source inputs: `pyproject.toml`/`uv.lock` pin the SDK and accepted accounting Core. Installed fixture and guard changes are listed by `git diff --name-status 533c7f6c -- tests`; no plan was assigned without a draft PR.

## Artifacts and resource ownership

TC2 owns `.venv` (~97 MiB), `evidence/tc2-sdk` (~1.1 MiB), and `/home/ts/.cache/agent-scratch/toad-tc2-sdk-20260929` (~1.7 MiB). Disposable fixture directories retire with TemporaryDirectory; test-owned processes are bounded and retired by the existing runner. Persistent small failure/pass receipts remain for review. Default/global activation still belongs to the parent; this worker has not modified it. This receipt does not claim #202 warm-tab or #211 canonical-turn issues are finished. Remove the env/scratch after review and activation when no process references them. No volatile worktree, global reset/clean, or edits in another worker's WT.
