# T8 small boundaries — ready for paired integration

**PR115:** https://github.com/OpenHCSDev/toad/pull/115
Owner Pascal. Tree `/home/ts/wt/toad-t8-small-boundaries-20260928`, branch
`refactor/t8-small-boundaries-20260928`. Production checkpoint `9aa0c65`;
current-main reconciliation `c80577d` includes fork main `60a87e0` / PR112.
PR244 is handed off; Darwin retains package integration. No package edits here.

## Complete T8 source/caller closure

1. **Terminal environment:** `terminal_environment.py` owns the six immutable
   variables and launch-time shell selection. `shell.py` and
   `widgets/command_pane.py` consume it; explicit extra env precedence preserved.
   Deleted both duplicate assignment blocks and constructor-time shell lookup.
   The plan's reported import-time SHELL access was actually a guarded demo;
   that demo now uses the same declaration.
2. **Saved sessions:** `db.py` declares Session through existing core TypedTable;
   schema, inserts, strict row reads and field updates derive from it. SessionMeta
   owns Path cwd and the existing external agent_data snapshot needed for resume.
   SqlStorage/JsonStorage use FieldCodec subclass SessionCodec solely for Path and
   datetime scalar encoding. No copied table/JSON engine, new registry, alias,
   dual format, or data conversion. The durable column `meta_json` retains its one
   external name but contains SessionMeta internally. SQLite session transactions
   run on workers; the UI event loop remains free while a real writer holds SQLite.
   Deleted Session TypedDict, misspelled promot_count, both cast(dict(row)) reads,
   hand-written session schema/INSERT/UPDATE plumbing, raw metadata read-modify-write
   and metadata JSON parsing in all consumers. Updated ACP agent, app launcher,
   resume modal, store screen and project-change consumers plus their fixtures.
3. **Danger:** nominal DangerLevel implementations own highlights and path
   escalation. CommandVisitor uses bashlex's visitor, including nested substitutions;
   known external command data remains. Deleted kind-string recursion, hasattr,
   enum/member switches, unused aggregate max result and dead DangerWarning module.
   Prompt consumes spans directly. Input redirection/descriptor duplication is not
   mislabeled as a filesystem write; write redirection still identifies outside paths.

## Acceptance

- `boundaries-current-main.log`: **6 passing** focused tests, including current
  durable schema load, typed metadata roundtrip, fresh schema, preserved agent
  definition during project update, strict invalid-count rejection, real SQLite
  contention with responsive event loop, actual bashlex spans and source guards.
- `mounted-combined.log`: real mounted CommandPane PTY sees all six variables;
  SessionResumeModal displays and returns typed records. Read-only SQLite backup
  of **all 46 original sessions** preserves identities, prompt counts, directory
  and full agent definitions; copied rows unchanged after decoding.
- `acp-session-title.log`: ACP creation metadata, saved title, visible tab title,
  existing-session load and identity-default case pass in mounted local fixture.
- Existing providers/package proof was not rerun; no provider calls, live writes,
  service restarts, or installed mutations. Temporary roots/copies are owned and
  cleaned after exit. Failure receipts remain; no silent replacement of failures.

## Required paired integration (concrete, not a T8 implementation hold)

Mounted acceptance used own integration tree
`/home/ts/wt/toad-t8-l0a-acceptance-20260928`, `d186c9e`, combining T8 with
**PR107 head2475f21** and parent core source (latest recorded `a732577`).
Current installed older core lacks Column.auto_increment; current Toad main
imports removed OBSERVATION_INTERVAL against newer core. PR107 already owns
those caller migrations: use it and the newer TypedTable core in the quiet rollout.
Do not add aliases or reinstall the old core to hide the seam.

One merge conflict with PR107: its deletion of `DB.session_delete` **wins** once
its UI purge caller is removed. The integration tree preserves that deletion;
PR115 retains the method only because current fork main still calls it. T8 tests do not retain that removed API as an acceptance requirement.
No other production conflict occurred. Parent owns pins and installation.

## Reproduction

Focused source:
```
PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src \
TMPDIR=$PWD/.artifacts \
/home/ts/.local/share/agent-comms/runtime-watcher-20260928/bin/python tests/test_t8_boundaries.py
```
Mounted commands use the same environment in the combined tree:
`tests/t8_mounted_pilot.py` and `tests/initial_session_title_pilot.py`.

## NRA and packaging

Full-context NRA completed in 54.4s with Python3.14 (the NRA checkout's Python3.11
cannot parse current Toad syntax; its failed receipt is preserved). This NRA
version does not emit a `scan_status`/analyzed-detector-count field. The complete
raw report is compressed in `nra-current.json.gz`, summary in `nra-summary.json`.
Three supporting signals point at existing core TOOLS, Agent._apply_session_update,
and TOOL_CALL_CONTENT; no mapping_read/unmodeled_record_shape findings reported.
Those belong to separately assigned tool/ACP/rendering surfaces, not proof that
all refactoring is complete. T8 acceptance rests on caller/deletion guards and
actual persistence/UI paths above, not a blanket zero-findings claim.

Exact successful invocation:
```
PYTHONPATH=/home/ts/code/projects/nominal-refactor-advisor \
/home/ts/.local/share/agent-comms/runtime-watcher-20260928/bin/python \
-m nominal_refactor_advisor src/toad/db.py src/toad/danger.py \
src/toad/terminal_environment.py --context-root src/toad \
--context-root /home/ts/wt/comms-acp-saved-session-startup-20260928/src/agent_comms \
--parse-workers 1 --analysis-workers 1 --cache-dir .artifacts/nra \
--scan-budget-seconds 120 --json --raw-findings --json-payload full
```

Wheel built successfully (no installation):
`.artifacts/dist/batrachian_toad-0.6.20-py3-none-any.whl`.
The wheel is T8 source on fork main; quiet installed acceptance must first pair
PR107/current core as explained above. Owned copied DB/temp roots were removed
by exited fixture contexts; generated NRA cache cleaned, one wheel retained.
