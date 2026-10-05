# Retired T4 replay consumer

Base: merged Toad #469 `289f1c6cd7667abf985ddba265d6469a95e3ea48`.
The original five production roles remain source-closed as recorded by #469.
This checkpoint deletes one unconsumed executable and its current instructions.

## Deleted family

`tools/performance/replay_state.py` wrote retired `App._open_tab_order` and
reconstructed views through removed `CoordinationUpdate`, sidebar/category
declarations, `new_session_screen`, `on_coordination_update` and
`open_comms_session`. It also maintained its own reconstructed App/view state,
private temporary wire and legacy-watch control. Its `main`/CLI, reconstruction,
mock patches and replay observation lifetime are deleted together; no replacement
adapter, state, alias or replay framework is introduced. This removes the old
authority instead of relocating it (IMPL-13, AGENT-6).

Complete tracked-source lookup found no import/caller or registered command
targeting this executable. Its only current executable links were the performance
README spinner option and headless replay section; those instructions are
removed in the same change. `capture_live.py` dynamically chooses the fixed
`capture_state`/`capture_screen` sources and original sidebar observer;
`capture_state.py` selects the original scroll-travel observer. Neither selects
replay. The historical navigation-allocation audit records a 13-view result at
its original source and is unchanged. Saved-data analyzers, captured data and raw
evidence are unchanged.

`CALLERS.json` records the original Package AST pass: 41 Toad tool modules,
398 Toad test modules and 373 Core test modules parsed, with zero omissions.
Tracked Git lookup also covered source, workflows, package configuration and
documentation. The source-head hashes and preserved consumer hashes are bound
there. No scanner or application import was added.

## Historical MCP family retained

`native_permission_ui.py` imports `mcp_observation_fixture.py`. Both still depend
on retired update declarations and Agent/view fields. The standalone
`typed_comms_command_pilot.py` likewise remains an unqualified old producer and
consumer. This checkpoint keeps all three intact.

There is a genuine external selection seam: Core
`tests/test_mcp_acceptance.py::_observer` reads `AC_MCP_TOAD_ADAPTER`, imports the
supplied path with `spec_from_file_location`, and enters its `open_observer`.
Core `tests/mcp-acceptance.md` documents that contract. No named default points
to these Toad controls, but arbitrary externally supplied paths cannot be
resolved from tracked source. Their lack of current06/S4 callers therefore
does not prove the entire historical adapter family unconsumed. Toad pytest
also declares `python_files = ["*.py"]`; collection remains a source consumer,
not behavioral qualification. No removed update/Agent compatibility is revived.

Original Heis's safe-checkpoint answer identifies current06's path as
`history_edge_scheduling_pilot --record-useful-paint` ->
`original_turn_resource_real_installed_pilot.main(readonly_capture=...)`.
That pilot borrows only l0a `until`/`response_painted` and saved
`screen_paint`/`submit_editor`; its read-only branch does not enter l0a `main` or
`retire_surface`. Current06 and current S4 do not borrow the retired replay or
these historical MCP controls. Heis reserves the current l0a assertion migration
in the normal #468 continuous-integration successor; it is outside this change.

## Exact scope

Only the executable and its current README instructions change. All production,
test, package/pin and recorder source is unchanged from the base. Frozen #469,
#468 and current06 helpers are not edited. The only post-deletion sanity is
source diff/whitespace and preserved-byte checking; there is no remaining edited
Python file to compile. No test, application import, prefix, build, native/SDK,
provider, input, session, public operation or runtime purpose is used.

This is source deletion, not live continuous/TC1/performance acceptance. Historic
results retain their original strength; they are neither replayed nor promoted.
