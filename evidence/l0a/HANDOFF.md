# L0A paired Toad caller closure

Paired core: OpenHCSDev/agent-comms#235 plus #238 (integrated by parent #229). Branch refactor/round2-l0a-callers starts from Toad main 511a1a2. Parent owns merge, D22 conversion and quiet installation.

## Scope

- Five Goal consumers in acp/agent.py and screens/goal_details.py now decode the current typed Goal with FieldCodec. Actual external ACP framing is preserved.
- app.py removes retired comms_delete progress/dispatch and SessionDelete handler. Delete the now-unused SessionDelete event and DB.session_delete operation.
- Context menu expectations remove delete; purge-exclusive pilot sections are deleted. Closing attached views retains the owner and saved session. Existing deliberate incarnation replacement tests use registry.remove only as test setup; their stale-basis assertions are retained.
- Goal owner/UI pilots keep all temporary files and screenshots under this owned worktree and clean them after execution.
- Pin agent-comms to published core #238 candidate 2eb571b. This pair cannot install on unconverted old saved roots.

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
