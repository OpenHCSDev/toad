## Paired L0A readiness: current parent integration passes

Core parent branch a5809ab169638eff2b0b0570f21261e15d6a7623 (contains
PR241 92b42ba and Darwin S9 73c9dbc) plus Toad aafd19c runtime:
**paired L0A ready for parent integration/activation**. Installed candidate wheels,
notification-only acceptance exits 0. Actual Toad -> ACP subprocess -> detached
owner -> prepared Pi native RPC -> one loopback HTTP request -> IGNORE -> visible
`Checked — no response (1)`. Participant active/idle and real owner navigation pass.

Evidence: evidence/l0a-parent-notification. Core pin is the tested parent a5809ab.
Toad includes the post-4b15e57 navigation fix in2844f66; integrate the full PR107
head, not only4b15e57. No waiting on separate hotfix242. No live activation here.
Parent owns publishing its integrated core, final quiet cutover/install and activation.

Only notification acceptance reran on this parent. Earlier queue, DM, cold reattach,
stopped-owner reopen and idle results remain at their recorded candidates. This
is the requested paired closure decision, not a claim that the entire suite ran
again on a5809ab. No paid calls or mocked native/notification callbacks.

### Earlier receipts (superseded candidate heads retained for provenance)

## Installed notification acceptance closed

Core PR241 92b42ba + Toad 2844f66 candidate wheels: focused
`tests/l0a_native_installed_pilot.py --notification-only` exits 0.
Actual mounted Toad -> ACP subprocess -> detached owner -> prepared Pi native RPC
-> local HTTP provider (one request) -> channel IGNORE -> visible
`Checked — no response (1)`. Active roster and return to idle both observed;
real owner navigation passes with ProcessIdentity. No mocked ACP/native callbacks
or notification projection, no paid calls. Logs in evidence/l0a-notification.

Toad core pin advances to the tested published 92b42ba. Parent owns final merged
integration pin, durable cutover, quiet install and live activation. This focused
receipt does not assert the complete suite ran on 92b42ba; prior queue, DM, cold
reattach, restart and idle evidence remains at its recorded candidate. None was
rerun for this notification fix. The dependency described below is now resolved.

## Latest caller audit: thread navigation

Removed one remaining production call to the deleted OwnerLifecycle._process_alive:
ThreadNavigationRequest now reads Thread.process_alive, the ProcessIdentity owner.
Updated 39 behavioral UI fixture files from Thread(pid=...) to ProcessIdentity.capture;
removed the same obsolete liveness call from e2e_pty. OS/ACP PID projections remain
where the external contract still requires them. Guard now rejects bare-PID Thread
fixtures and production _process_alive calls. No durable or runtime store changes.

Local checks: navigation_preparation_pilot and pending_thread_open_pilot both pass
against source Toad plus installed parent89e420b core. Caller guard and E9/F lint pass;
full repository lint/full UI suite were not rerun. No changed performance invariants.
Source change is +1/-1; fixture migration preserves existing behavior assertions.

The installed native pilot now exposes --notification-only, reusing the existing
fixture and channel assertion, with exactly one loopback request. It additionally
checks real attached owner navigation through ThreadNavigationRequest. This mode
has not yet run: Nietzsche owns PR241 history_views.py stale-table/process-liveness
fix, still unpublished at 1e152bf when this update was written. Existing retained
failure remains evidence, not a waived assertion. Parent can integrate this caller
fix independently; notification acceptance is the only dependency under test here.

# L0A paired Toad caller closure

Paired core: OpenHCSDev/agent-comms#235 plus #238 (integrated by parent #229). Branch refactor/round2-l0a-callers starts from Toad main 511a1a2. Parent owns merge, D22 conversion and quiet installation.

## Scope

- Five Goal consumers in acp/agent.py and screens/goal_details.py now decode the current typed Goal with FieldCodec. Actual external ACP framing is preserved.
- app.py removes retired comms_delete progress/dispatch and SessionDelete handler. Delete the now-unused SessionDelete event and DB.session_delete operation.
- Context menu expectations remove delete; purge-exclusive pilot sections are deleted. Closing attached views retains the owner and saved session. Existing deliberate incarnation replacement tests use registry.remove only as test setup; their stale-basis assertions are retained.
- Goal owner/UI pilots keep all temporary files and screenshots under this owned worktree and clean them after execution.
- Pin agent-comms to parent #229 candidate 89e420b. This pair cannot install on unconverted old saved roots.

## Stores and cutover

No Toad store/schema or external Pi/ACP format change. Toad saved sessions, archive/history and session transcripts remain durable and are retained; the only database change is deletion of the unused purge operation. Core registry/goal-history representation requires parent's D22 one-shot conversion before installation. Runtime counters/owners reset at that quiet boundary without replay. No production restart, install or data mutation performed here.

## Checks

Built both real wheels, installed only into .artifacts/candidate using the existing Python3.14 runtime for dependencies. The actual RuntimeServer pilot passes set/edit/stale revision rejection, history, snapshots and ACP metadata publication against those installed wheels. No mocked codec or provider call.

Passed against installed candidate wheels:
- `goal_edit_owner_pilot.py`: actual owner set/edit, stale CAS rejection, history, snapshots and ACP metadata.
- `goal_server_poll_pilot.py`: mounted actual Toad UI, goal history/editing/standby, layout, owner outage/recovery and bounded reads.
- `l0a_archive_history_pilot.py`: click actual declared Archive menu; retain wire messages, goal revisions, incarnation, transcript and Toad saved session.
- `right_comms_integration_pilot.py`: relationship tools, mounts, ordering, tab reuse and stale relationship rejection.
- `comms_pilot.py`: complete interaction pilot, with its local deterministic backend fixture (not provider acceptance); retained attachment, owner lifecycle, tab/menu and saved-session checks pass.
- `l0a_callers_guard.py`: AST scans all production Toad callers; no removed Goal reader, thread purge, SessionDelete or saved-session delete method remains.

`dm_rebind_paint_pilot.py` now PASSES against core #238 with the original pending-count assertions retained. Its Thread fixture now captures real ProcessIdentity. Parent #229 owns ReadLedger rename-alias integration.

Imports proved to be from `.artifacts/candidate` for both packages; see package-origin.json. No live install is claimed. All owned code/caller changes are published; integrated acceptance and activation remain with the named parent/Lovelace dependencies.

## Ownership

Lovelace core #232 owns deletion of unused Thread.from_registry/registry_created_at/session_created_at; coordination sent to that PR. Parent owns core #229 and activation. No further subagents or live worktree changes.

## Change counts

Toad production source: +8 / -70 lines (net -62). Test counts include deleted purge-only sections, migrated caller setup and new real archive UI/deletion guard checks; exact counts are in change-counts.json. Core production source: +58 / -260 (net -202); core ratchet -2 type identity, 0 long boolean chains, -3 string subscripts. Core 73 focused checks and all 8 marked guards pass.

## Current queue and ProcessIdentity closure

- Delete the old top-level agentComms queue reader, dead PromptQueueUpdate type and no-op handler. Keep queueBinding/queueState, scoped InputStarted, missing-evidence feedback and local failed-request draft recovery. ACP external framing unchanged.
- Delete obsolete event-order baseline probe; its useful duplicate/start/stale/foreign/retired-agent/draft assertions are consolidated in queue_view_pilot using the retained current contract. No old-format producer or exception mode remains.
- Rewrite send_status_pilot to current exact-ID state: both keyboard shortcuts paint before transport completion; scheduling requests keep remote rows; exact start removes one of two equal-text inputs; restored snapshots never overwrite local drafts.
- Replace old native-stream patched backend pilot with actual ACP queued admission/emission/retirement delivered into a mounted Toad. Only transport and held-backend/start-event are fixtures; no native provider consumption claim. Checks production UNKNOWN persistence, duplicate-ID start handling, no removed emitter keys, null feedback, read-only restoration and admission replacement.
- Actual candidate startup found the removed core OBSERVATION_INTERVAL import in three widgets. Move the UI refresh setting into existing toad.constants and update comms_sidebar/comms_chat/observed_thread_activity. Preserve existing interval; no core compatibility export.
- Current built wheel passes: queue_view_pilot, send_status_pilot, dm_rebind_paint_pilot and queue_view_backend_pilot. Source AST caller guard passes. Evidence files end in -current.txt. Earlier goal/archive/source checks above belong to their recorded candidate revision; they were not rerun or claimed as latest full-suite acceptance.
- This follow-up adds/deletes runtime +9/-23 and tests +271/-472. The full paired branch remains net deletion. Parent owns final pin to merged main and quiet D22 activation. No installed live environment changed.

Final candidate pin2eb571b retested with built core/Toad wheels: DM rebind, actual queued ACP producer-to-mounted-UI, and current request/owner/stop/draft rollback fences all PASS (-final.txt). No native provider execution or live installation is claimed.

## Installed native acceptance against parent89e420b

Current branch pin:89e420b14d5e8a7839bb9d119f2fc75a2a6fb8f3. Core built from own persistent detached worktree ~/wt/comms-l0a-native-stage-20260928; both wheels installed only under this Toad worktree's .artifacts/candidate. Existing prepared Pi extensions package was verified by the installed core. The fixture uses the existing OpenAI-compatible loopback SSE pattern with isolated selected-offline/fixture credentials; no paid provider calls, no installed live environment changes.

`tests/l0a_native_installed_pilot.py` exercises real Toad ACP stdio -> detached core owner -> prepared Pi -> loopback model, not injected native callbacks. Passing boundaries in latest run:

- Native initial and queued inputs; queued UI ID maps through the durable disposition to the saved Pi input ID; disposition is started and queue row disappears without changing the local draft.
- Cold ACP reattach to the same detached owner, saved transcript displayed, no extra model request.
- Actual mounted DM send and native response.
- Actual channel triage with visible busy participant, then idle roster.
- Explicit Toad Start after stopping the isolated owner; fresh process identity, saved transcript reattach without replay, then one new native input succeeds.
- Idle sample2.07s: owner0.05 CPU-seconds, UI0.38 CPU-seconds, zero model requests. This short fixture sample is not a scaled or workstation-wide performance claim.
- Clean exit after the watcher fix below. Prior narrower complete run exited0; latest complete script exits1 for the deliberately retained core failure below.

Actual cold reattach exposed an owned Toad leak: watch_agent_ready replaced an existing non-daemon DirectoryWatcher and lost its cleanup reference. Reuse the existing watcher; sync_project_path remains its replacement owner. The real acceptance asserts watcher identity survives reattach and process exit completes. Runtime delta+1/-1; pin+1/-1; one new455-line end-to-end fixture replaces no production mechanism. No unchanged index/performance invariants were rerun.

**Parent-owned remaining blocker:** history_views.py:163 in core89e420b directly queries retired table native_runtime_inputs rather than NativeRuntimeInput's declared table. After native channel triage, both actual UI MessageNotifications and direct core message_notifications fail with OperationalError('no such table: native_runtime_inputs'). The UI correctly shows unavailable; the expected Checked/no-response assertion remains failing. Reported to parent229 with exact site and evidence, also still present in published d083703 when checked. No compatibility table, skip, or relaxed assertion added. Full paired acceptance is not complete until that core query is corrected and this installed pilot passes.

Evidence: evidence/l0a-native/{receipt.json,native-reopen.txt,native-final.txt,native-session.jsonl,toad-acp.log,acp-debug,acp-debug.log,callers-guard.txt}. The source guard still passes. Parent owns durable D22 conversion, final merged-main pin and quiet activation.
