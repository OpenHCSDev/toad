# L0A paired Toad caller closure

Paired core: OpenHCSDev/agent-comms#235. Branch refactor/round2-l0a-callers starts from Toad main 511a1a2. Parent owns merge, D22 conversion and quiet installation.

## Scope

- Five Goal consumers in acp/agent.py and screens/goal_details.py now decode the current typed Goal with FieldCodec. Actual external ACP framing is preserved.
- app.py removes retired comms_delete progress/dispatch and SessionDelete handler. Delete the now-unused SessionDelete event and DB.session_delete operation.
- Context menu expectations remove delete; purge-exclusive pilot sections are deleted. Closing attached views retains the owner and saved session. Existing deliberate incarnation replacement tests use registry.remove only as test setup; their stale-basis assertions are retained.
- Goal owner/UI pilots keep all temporary files and screenshots under this owned worktree and clean them after execution.
- Pin agent-comms to published core #235 candidate. This pair cannot install on unconverted old saved roots.

## Stores and cutover

No Toad store/schema or external Pi/ACP format change. Toad saved sessions, archive/history and session transcripts remain durable and are retained; the only database change is deletion of the unused purge operation. Core registry/goal-history representation requires parent's D22 one-shot conversion before installation. Runtime counters/owners reset at that quiet boundary without replay. No production restart, install or data mutation performed here.

## Checks

Built both real wheels, installed only into .artifacts/candidate using the existing Python3.14 runtime for dependencies. The actual RuntimeServer pilot passes set/edit/stale revision rejection, history, snapshots and ACP metadata publication against those installed wheels. No mocked codec or provider call.

Mounted UI pilot and archive/history acceptance are running; not claimed complete yet. The existing DM rebind pending-count behavior depends on parent #229 ReadLedger integration; assertions are not weakened.

## Ownership

Lovelace core #232 owns deletion of unused Thread.from_registry/registry_created_at/session_created_at; coordination sent to that PR. Parent owns core #229 and activation. No further subagents or live worktree changes.
