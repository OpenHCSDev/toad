# Tests

How Toad's tests are built, which layer each one belongs to, and what happened to every test that was failing when the suite was consolidated (2026-10-11).

## Why

The suite was 181 standalone scripts ("pilots"), each building its own temporary directories, environment, app, fake agent, wait loops and screen reads, plus 29 pytest files. 172 of 363 ids failed, and almost none of those failures said anything about the product: scripts read environment variables only an outside harness set, reached private fields that had moved, or tested code that had been deleted. A failure has to mean the product is wrong.

## Owners

Everything a test shares lives in `tests/support`. Tests import it; they do not rebuild it.

| Fact | Owner | A test writes |
|---|---|---|
| Private directories and environment of one test | `support.roots.Roots` | nothing (asks for `workspace`) |
| One process per app test, its timeout, stopping what it left running | `tests/conftest.py` (`OwnProcessTest`), `support.processes` | nothing |
| The project, its comms wire, declared threads | `support.workspace.Workspace` | `workspace.thread("alpha", "team")`, `workspace.comms` |
| Starting Toad headless and waiting until it is usable | `Workspace.app()` | `async with workspace.app() as ui:` |
| Waiting for a condition, with the screen in the failure | `Ui.until`, `Ui.until_shows` | `await ui.until_shows("text")` |
| What the screen shows, tabs, focus, draft, links | `support.ui.Ui` (questions any frontend can answer) | `ui.visible_lines()`, `ui.tabs()`, `ui.link_at("@alpha")` |
| Keys, typing, clicks, resize | `Ui.press`, `Ui.type`, `Ui.click`, `Ui.resize` | `await ui.click("Float")` |
| A scripted agent process (official ACP SDK over stdio, no model) | `support.agents.peer`, `support/peers/` | `workspace.app(agent=peer("echo"))` |
| What the agent received | `Workspace.received()` (the peer's own record) | `workspace.prompts_received()` |
| Things only some machines have (native package, terminal emulator, X server) | `support.requirements` fixtures | asks for `native_package`; absent means a skip that names the requirement |
| Textual widgets, pilot and painted regions | `TextualUi.textual`, `.conversation`, `.painted()` | only in `tests/textual` |

## Layers

The directory says what a test depends on. `tests/guards/test_test_layers.py` enforces it from the imports.

| Directory | Tests | May use |
|---|---|---|
| `tests/model` | Behaviour with no interface: Core answers, line blocks, view models, codecs, session and agent protocol objects | `agent_comms`, `ui_theme`, frontend-neutral `toad` modules, `tmp_path`. Never `textual`, `toad.widgets`, `toad.screens`, `toad.app` |
| `tests/app` | The running app, asked only questions a second frontend could answer | `workspace`, `Ui` questions, Core reads. Never `textual`, widget classes, `ui.textual` |
| `tests/textual` | Behaviour owned by the Textual frontend: paint, layout, strips, compositor, widget classes. The module docstring says which frontend behavior it exercises | everything, through `ui.textual` |
| `tests/native` | The real native agent package | `native_package` (skips with its reason when absent) |
| `tests/terminal` | Toad in a real pseudo-terminal | `terminal` (skips when the emulator is absent) |
| `tests/guards` | Source checks: deleted mechanisms stay deleted, layers stay separate | `ast`, the source tree |

When a behaviour does not depend on Textual but no neutral owner exists yet, add the question to `Ui` (abstract, then the Textual answer) rather than reaching into a widget from the test. A new question is worth adding when a second frontend could answer it and more than one test asks it.

Timing thresholds are not asserted in this suite. It runs niced on shared cores, so a millisecond bound fails for reasons that are not the product. Frame time and input response are measured in the running application by `tools/performance`. A test here asserts the count of work (no second layout pass, one render) instead.

## The four resolutions

Every id that failed is resolved one of these ways, recorded in the table at the end:

- **deleted**: it tested code that no longer exists, or only wrote record files.
- **rewritten**: the behaviour still exists; the test now asks the owner of the fact.
- **fixed**: the product was wrong; the defect is named with its fix or its owner and reproducer.
- **requirement**: it needs something this machine may not have; it skips with that name instead of raising.

An assertion is never weakened to pass. Where an expectation changed, the row says what changed in the product and why the new expectation is right.

## Conversion pattern

Before (`tests/tab_order_pilot.py`, 45 lines, failing with `UnknownModeError: No known mode 'session-1'`):

```python
async def main():
    with tempfile.TemporaryDirectory(prefix="toad-tab-order-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.registry.declare(Thread("owner", frozenset(), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 32)) as pilot:
            await pilot.pause()
            first = app.selected_mode
            channel = await channel_target("#all").open(NavigationContext(app, first, root, "owner"))
            second = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
            expected = [first, channel, second]
            for mode in expected * 2:
                await app.switch_mode(mode)
                await pilot.pause()
                assert [tab.mode_name for tab in app.open_tabs] == expected
                assert [label.id for label in app.screen.query_one(SessionsTabs).query(SessionLabel)] == expected
            ...

if __name__ == "__main__":
    asyncio.run(main())
```

After (`tests/app/test_tab_order.py`, 19 lines, no Textual):

```python
async def test_interleaved_tabs_keep_opening_order_through_selection_and_close(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(140, 32)) as ui:
        first = ui.selected_tab
        channel = await ui.open_channel("#all", actor="owner")
        second = await ui.new_session()
        expected = [first, channel, second]
        for identity in expected * 2:
            await ui.select_tab(identity)
            assert [tab.identity for tab in ui.tabs()] == expected
            assert ui.selected_tab == identity
        ...
```

The test failed because it switched tabs through Textual's `switch_mode`, which stopped being how Toad selects a session. The owner of that fact is now the harness, in one place.

Steps for one file:

1. Read what it claims (docstring, final `print`) and what it asserts.
2. Decide the layer from what the assertions need, not from what the old code happened to import.
3. Replace the setup with `workspace` and `workspace.app()`. Delete the temporary directory, the environment block, `asyncio.run`, the `__main__` block, the success `print`, and any writing of record files.
4. Replace fixed pauses before an assertion with `ui.until(...)` on the fact being awaited.
5. Replace screen and widget reads with `Ui` questions where the layer is `app`.
6. One behaviour per test function, named for the behaviour.
7. Rename the file and its helpers out of the old vocabulary (custody, admission, receipt, original, provenance, publication).
8. Run it. A failure now is either a stale expectation (say what changed) or a defect (name it).

### Edits a new test needs

| | Before | After |
|---|---|---|
| Lines before the first line about the behaviour | 14 to 20: imports of `asyncio`, `os`, `tempfile`, `Path`, the app; temporary directory; four environment variables; wire; app; `run_test`; first pause; `main`; `__main__` block; success print | 2: the function signature with `workspace`, `async with workspace.app() as ui:` |
| Decisions the author makes | where the roots go, which variables to set, which app class and stylesheet, how long to pause, how to read the screen, how to stop what was started, the script name suffix that gets it collected | which layer directory |
| Places that change when Toad changes how a session is selected, a tab is opened or the screen is read | every script that did it (124 built the app, 78 read the compositor) | `support/ui.py` |

## Running

```
python -m pytest tests -n 6                 # everything
python -m pytest tests/model tests/guards   # no app, seconds
TOAD_TEST_NATIVE_PACKAGE=/path/to/pi-coding-agent python -m pytest tests/native
```

Every test that asks for `workspace` runs in its own interpreter, so the suite is safe under `-n`. A failing app test prints the screen it last saw and keeps its roots under `/var/tmp/toad-test-*`. A test whose requirement is missing (the native package, the `pyte` terminal emulator) is skipped with the requirement's name; nothing else skips.

While frame time is being measured on the development machine, run at most three single pytest processes at once, pinned with `taskset -c 0-3 nice -n 19`.

## Open defects

`tests/open_defects.toml` lists the tests that fail because the product is wrong: the defect in plain words, its owner, and the tests that reproduce it. The runner expects each listed test to fail. A listed test that passes is reported as an error until its entry is removed, so the list cannot go stale. An entry marked `intermittent` reproduces only on some runs; for it, passing is not an error. Do not add an entry without a named defect and owner, and never add one to quiet a test you have not read.

At the time of the consolidation the list holds 18 defects covering 32 tests:

| Defect | Tests | Owner |
|---|---|---|
| `agent-text-click` | 8 | frame-time / line-view owner (perf/line-history) |
| `shared-channel-tab` | 3 | Tristan (product meaning), then the comms UI owner |
| `relationships-revision` | 2 | Core (agent-comms) owner for the answer, then Toad's thread_comms_source |
| `filter-selection-before-layout` | 1 | frame-time / line-view owner (perf/line-history), transcript_history.py |
| `route-publication-while-toad-runs` | 1 | Core (agent-comms) route owner, with Toad's CoordinationAccess |
| `key-burst-order` | 1 | unassigned: Toad input handling (widgets/conversation.py is being edited by the frame-time agent) |
| `command-hint-refresh` | 1 | unassigned: Toad prompt (widgets/prompt.py, slash completion) |
| `history-admission-growth` | 1 | frame-time / line-view owner (perf/line-history) |
| `filter-reapplied-finds-nothing` (intermittent) | 1 | frame-time / line-view owner (perf/line-history), transcript_history.py |
| `session-title-precedence` | 3 | unassigned: Toad sessions (acp/agent_session.py; widgets/conversation.py is being edited by the frame-time agent) |
| `model-picker-highlight` | 2 | theming owner (the ui-theme colours work), widgets/model_switcher.py |
| `reader-row-after-trim` (intermittent) | 1 | frame-time / line-view owner (perf/line-history) |
| `tool-diff-after-modal` (intermittent) | 1 | unassigned: Toad tool output (tool_output.py, widgets/tool_call.py) |
| `late-goal-notice` | 1 | Core goal owner (agent_comms GoalSnapshot), then the Toad goal bar (GoalObservation.receive) |
| `late-answer-drawn-twice` (intermittent) | 2 | frame-time / line-view owner (perf/line-history), transcript_publication.py |
| `reader-row-frame-during-page-load` (intermittent) | 1 | frame-time / line-view owner (perf/line-history), transcript_history.py |
| `select-mounted-before-its-label` (intermittent) | 1 | Textual fork owner (OpenHCSDev/textual, widgets/_select.py); reached from toad/screens/permissions.py |

## What the suite does not cover

These had a script before and have no test now. Each needs something the suite cannot supply yet.

| Behaviour | What it needs |
|---|---|
| Serving Toad in a browser | playwright and Chromium |
| A native session tab in a real `st` terminal | `st`, `xdotool`, `python-xlib`, Pillow and a private display |
| Copy and paste through a real terminal | a private display, `xclip`, and a terminal run of Toad |
| Editor keys through a real terminal | a terminal run of Toad whose editor state can be read without record files |
| Messages queueing while a native turn is held | a way to ask Core to hold a native turn |
| `WorkerStatic` (drawing prepared off the UI thread) | a test of what it shows, not of its private fields |
| Choosing the agent of a saved thread with a real provider | a live acceptance run, not a suite test |

Timing budgets are not asserted anywhere in the suite; frame time and input response are measured in the running application (`tools/performance`).

Three modules in `tests/support/core_adapters/` are loaded by agent-comms' own tests by file path. Moving them means changing those paths in agent-comms in the same step.

## Resolution of the failing ids

The starting point was `main` on 2026-10-11 against the published runtime: 363 ids ran, 172 failures were reported (171 distinct ids; one of them also failed a subtest) and 191 passed. Seven more ids in `guards/test_transcript_publication.py` were deselected because two of them hung. The table has one row per old file with a failing or hanging id, 173 ids in all.

| Resolution | Ids |
|---|---|
| rewritten | 100 |
| rewritten (needs native package) | 17 |
| rewritten (needs a terminal emulator) | 1 |
| fixed (the product was wrong) | 4 |
| fixed in part, the rest an open defect | 3 |
| open defect (kept as a named requirement) | 13 |
| deleted | 30 |
| not converted (deleted, gap listed) | 5 |
| total | 173 |

"Rewritten" covers both a test that was wrong about its own setup and one whose expectation was stale; the Reason column says which and what changed. "Open defect" is a rewritten test that still fails because the product is wrong; it is kept as a named requirement in `tests/open_defects.toml`. "Not converted" is a deleted script whose behaviour is listed under "What the suite does not cover".

| Old file | Ids | Resolution | Now | Reason |
|---|---|---|---|---|
| `acp_log_ui_pilot` | 1 | rewritten | `tests/textual/test_acp_log_view.py` | three tests (views/wrap/keyboard/resize/latest; Earlier/Latest paging and missing-file recovery; ordinary project file preview). The old test read the user's real log from an environment variable; it now writes a synthetic log with the same records. |
| `acp_specification_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/` | See the native rows: runs with a native package. |
| `agent_configuration_native_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_configuration.py` | The fixture model is now declared reasoning-capable, otherwise Pi keeps thinking 'off'; the level beside the model name is awaited (it follows ConfigurationChanged). |
| `agent_selection_configured_installed_pilot` | 1 | deleted | — | Forked a real saved thread on the live wire with a real provider: a live acceptance run, not something private roots can hold. |
| `agent_startup_failure_installed_pilot` | 1 | rewritten | `tests/app/test_agent_startup_failure.py` | Passed the agent as a dict; uses scripted processes and reads the screen. |
| `app_focus_latency_pilot` | 1 | deleted | — | Only printed timings. |
| `application_actions_installed_journey` | 1 | rewritten | `tests/textual/test_application_actions_in_the_running_app.py` | (settings screen, command palette, sidebar button, tab close); split into five tests, uses peer("completion"); notifications are kept via support/applications.record_notifications and the error toast is awaited with ui.until. |
| `attachment_request_pilot` | 1 | rewritten | `tests/textual/test_queue_request_results.py` | A replaced session request's late answer is refused to its caller (InvalidParams) and changes nothing; the old test expected it to return quietly. |
| `block_interaction_pilot` | 1 | rewritten | `tests/textual/test_block_menu_and_copy.py` | takes private_display_programs and starts Xvfb in a local fixture (DISPLAY set via monkeypatch). Kept user-input copy and paste-to-prompt, declared extra block copy and action, tool-call expand/collapse by key with check_action results, resize. |
| `browser_serving_pilot` | 1 | not converted | — | Needs playwright and Chromium; see "What the suite does not cover". |
| `catalog_actions_native_installed_pilot` | 1 | rewritten | `tests/textual/test_store_agent_actions.py`, `tests/model/test_terminal_request_arguments.py`, `tests/native/test_native_catalog_launch.py`, `tests/support/catalog.py`, `tests/support/catalog_steps.py` | The script wrote a catalog file into the installed package. The private entry is now added at the one catalog read (toad.agents.read_agents), decoded from the same TOML. Only the Store launch needs the native package. |
| `channel_any_mode_ui_pilot` | 1 | rewritten | `tests/textual/test_channel_any_mode.py` | The menu item now carries Core's one label, "Toggle member activity"; the old two labels were Toad's own. |
| `channel_display_basis_pilot` | 1 | rewritten | `tests/app/test_channel_display_basis.py` | Painted rows are asked as screen text plus Core seen_sequences; has_older/painted_keys became 'channel 9 not shown'. |
| `channel_mentions_pilot` | 1 | rewritten | `tests/app/test_channel_mentions.py` | Asserted before the mention candidates had loaded; waits for the list. |
| `channel_participant_publication_pilot` | 1 | rewritten | `tests/textual/test_channel_participants.py` | (ChannelParticipants widget, sys.monitoring count of prepare_participants on worker vs UI thread, kept as counts). Dropped: the ThreadView.presentation counter (no longer called by the participants path) and the loop-gap measurement (never asserted). |
| `channel_scope_expansion_pilot` | 1 | rewritten | `tests/app/test_channel_scope_expansion.py`, `tests/textual/test_channel_scope_rows.py` | App test waits on screen text with no explicit refresh; textual test keeps the explicit refresh and row/has_older checks. Both pass; the old AssertionError did not reproduce (old file used runtime_fixture refresh_comms). |
| `channel_visibility_observation_pilot` | 1 | rewritten | `tests/textual/test_hidden_channel_refresh.py` | (hidden view's refresh callback, reader pending set). The unused checkpoint_checks helper in the old file was dead code and is not carried over. |
| `checkpoint_source_pivot_pilot` | 1 | rewritten | `tests/textual/test_checkpoint_first_source.py` | Expected the saved answer as a response widget inside the history; history is drawn as lines, so the test now requires no live response widget left and the answer drawn exactly once. The covered live response is retired again since the answers-drawn-twice fix (agent_response.py). |
| `client_session_native_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_client_requests.py` | Same assertions; screenshots dropped. |
| `clipboard_native_pilot` | 1 | not converted | — | Needs a private X display, xclip and a terminal journey with a helper app; see "What the suite does not cover". |
| `cold_thread_latency_pilot` | 1 | rewritten | `tests/textual/test_cold_thread_return.py` | the held-render thread opening is now the shared step replay_with_pending_render in tests/support/textual_steps.py. Kept: loading indicator present, replay marker shown, loading gone, draft kept across four returns with and without background output. |
| `comms_scene_latency_pilot` | 1 | rewritten | `tests/app/test_cold_channel_open.py` | No wall-clock threshold existed (it only printed samples); the SceneProbe timing, prompt descendant counts and printed medians dropped. Kept: each cold channel shows its history and the composer is ready. |
| `context_native_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_context_measurement.py` | Same assertions. |
| `context_resume_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_context_resume.py` | (private native wire, no provider). The 'context unavailable' fact now names the real project as worktree instead of the wire directory. |
| `context_usage_pilot` | 1 | fixed | `tests/app/test_context_usage.py` | Product: usage reported while the tab was hidden was not shown on return for a generic ACP agent (fixed in acp/agent_controller.py). The old test hid it by refreshing by hand. |
| `core_events_native_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_editor_queue.py` | Same assertions. |
| `cursor_extent_pilot` | 1 | deleted | — | Tested update_live and document_viewport, which no longer exist. |
| `cursor_request_pilot` | 1 | rewritten | `tests/textual/test_cursor_request_results.py` | Same as attachment_request_pilot. |
| `default_route_admission_pilot` | 1 | open defect | `tests/native/test_child_route_environment.py`, `tests/textual/test_stale_route_writes.py` | Core no longer accepts a made-up package path, so the child-route tests take the real native package. The delayed-write case is open defect route-publication-while-toad-runs. |
| `default_route_cancel_pilot` | 1 | rewritten | `tests/textual/test_interrupted_send.py` | two tests (DM send cancelled in flight; a committed channel send stays unsendable under its identity until its message is drawn). The view's wire is message_history.source.comms; uses support/routes.py. |
| `default_route_pilot` | 1 | rewritten | `tests/textual/test_default_route*.py` | The app follows a route change on its once-a-second route check; the test waits for that instead of asserting at once. |
| `default_route_prompt_selection_pilot` | 1 | rewritten | `tests/model/test_agent_prompt_route.py` | The stale-route refusal moved from Agent.send to the admitted prompt path; the test goes through that path. |
| `default_route_retirement_pilot` | 1 | rewritten | `tests/model/test_route_publication_waits_for_agent_processes.py` | Model layer; agent built with support.agents.detached (AgentDefinition, not dict). |
| `dense_history_pilot` | 1 | rewritten | `tests/textual/test_dense_history.py` | Layer textual. Kept: each scroll to the top admits earlier records and the state accepts source work. Not carried over: widget budget and materialized_widget_count (gone), and has_newer/has_older after ten scrolls (came from widget-budget eviction; |
| `directory_watcher_visibility_pilot` | 1 | rewritten | `tests/textual/test_directory_watcher_visibility.py` | ui.conversation._directory_watcher, ui.new_session, ui.select_tab. |
| `dm_rebind_paint_pilot` | 1 | rewritten | `tests/textual/test_dm_peer_replacement.py` | (rows, ack_inflight); added Ui.open_direct_messages. |
| `editor_key_burst_pilot` | 1 | open defect | `tests/textual/test_key_bursts_move_focus_to_the_editor.py` | Backspace burst passes; the arrow-key burst is open defect key-burst-order. |
| `editor_key_terminal_journey` | 1 | not converted | — | Drove a helper app in a terminal and read its record files; see "What the suite does not cover". |
| `editor_key_workflow_pilot` | 1 | rewritten | `tests/textual/test_editor_keys_across_tabs.py` | Typing, arrows, backspace, delete and undo across click, park, return and tab clicks, with all old assertions. |
| `existing_thread_link_pilot` | 1 | rewritten | `tests/textual/test_existing_thread_link.py` | Both cases click a sender's name drawn in a chat (a channel, and a narrow direct chat); the separate link widget is gone. |
| `f4_declared_family_installed_pilot` | 1 | deleted | — | A record script bound to one saved session, a live thread and a machine path. |
| `file_path_preview_pilot` | 1 | open defect | `tests/textual/test_file_preview_tabs.py`, `tests/model/test_project_links.py`, `tests/textual/test_file_links_in_agent_text.py` | Preview tabs and link decoding pass. Links in drawn agent text are open defect agent-text-click. |
| `file_preview_latency_pilot` | 1 | deleted | — | A benchmark that patched a name no longer in that module. |
| `filter_mount_supersession_pilot` | 1 | open defect | `tests/textual/test_message_filter_switch_while_mounting.py` | Rewritten; the empty-filter case is open defect filter-selection-before-layout. Checks of per-fragment child mounting were about deleted widgets. |
| `first_frame_installed_terminal_journey` | 1 | fixed | `tests/terminal/test_first_frame.py` | Found the advertised-hint exit (fixed). Needs pyte. |
| `follow_stream_pilot` | 1 | rewritten | `tests/textual/test_follow_stream.py` | AgentResponse.append became append_fragment. |
| `fragment_divider_pilot` | 1 | rewritten | `tests/textual/test_fragment_dividers.py` | (imports toad.widgets). Saved history is lines, so one divider is asserted on the fragments' Divider line blocks; |
| `goal_edit_owner_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_goal_owner.py` | no app. Core's ACP server object in this process. |
| `goal_objective_edit_pilot` | 1 | open defect | `tests/native/test_native_goal_objective_edit.py` | Two cases pass; an older goal notice replacing the current one is open defect late-goal-notice. |
| `goal_resize_pilot` | 1 | rewritten | `tests/textual/test_goal_bar_resize.py` | split into four behaviours. Turn owner is now set by ui.conversation.turns.start_client(); the separator hand-over is waited for with ui.until because the bar updates it after a coalesced call_later. |
| `goal_retry_pilot` | 1 | rewritten | `tests/textual/test_goal_retry.py`, `tests/support/goals.py` | The hand-written fake agent is replaced by support.goals.ScriptedGoalOwner, a subclass of the real toad.acp.agent.Agent attached with ui.attach_agent. |
| `goal_server_poll_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_goal_bar.py` | four tests. The throbber's busy flag is computed now, so the 'busy indicator does not hide standby' stimulus raises busy_count instead of setting throbber.busy. |
| `goal_set_owner_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_goal_owner.py` | no app. Core moved the goal store to turns.goals.open_goal_store(). |
| `goal_standby_history_pilot` | 1 | rewritten | `tests/textual/test_goal_owner_views.py`, `tests/support/goals.py` | six tests over ScriptedGoalOwner (Agent subclass). Throbber busy is driven through view.busy_count (busy is computed); owner pushes are published on owner.events as CommsUpdated with the owner's session id. |
| `guards/test_goal_interaction` | 1 | rewritten | `tests/textual/` | Failed once under parallel load; passes alone (7 of 7) and in the full run. |
| `guards/test_live_output` | 1 | rewritten | `tests/guards/test_live_output.py`, `tests/textual/test_live_output_streams.py` | Blocks no longer hold a stream object, so the `_stream is None` checks went. The "retired source" update had been rebuilt with the view's own agent as publisher; it now comes from another agent. |
| `guards/test_t4` | 1 | rewritten | `tests/guards/` | The guard listed widgets/viewport_body.py, which was deleted. |
| `guards/test_t5` | 1 | fixed | `tests/guards/` | Product: session views looked their sidebar up by a copied id string (fixed in screens/main.py and screens/comms.py). |
| `guards/test_tool_output` | 1 | rewritten | `tests/textual/` | ToolCall takes a ToolCallStatus, not a dict. |
| `guards/test_tr0` | 2 | deleted | — | Guarded the standalone-script collector, which is gone; its path and skip checks live in guards/test_test_layers.py. |
| `guards/test_transcript_filter` | 1 | rewritten | `tests/guards/` | The guard listed two deleted modules. |
| `guards/test_transcript_publication` | 2 | rewritten | `tests/guards/`, `tests/textual/test_transcript_presentation_fencing.py` | The hang: a hand-written journal line with a string as assistant content made Core raise and the app close, and the test waited without a bound. Journals come from support.journals; waits are bounded. retire_presentations is a plain function now. |
| `history_anchor_geometry_pilot` | 1 | rewritten | `tests/textual/test_history_anchor_geometry.py` | An anchor must be something layout placed; anchoring an off-screen record is refused on purpose. |
| `history_availability_installed_pilot` | 1 | rewritten | `tests/textual/test_saved_history_availability.py` | Layer textual. Needed a captured ACP log from argv; now builds the saved page from AssistantTranscript events. |
| `history_mounted_budget_pilot` | 1 | open defect | `tests/textual/test_history_admission_budget.py` | Open defect history-admission-growth. |
| `history_prefetch_pilot` | 1 | rewritten | `tests/textual/test_history_prefetch.py` | Layer textual. Two tests (plain and filtered). The filtered fixture's routed message was lengthened (50 -> 150 paragraphs) so the filtered view stays taller than prefetch_distance, which the old widget heights did; an assertion states that. |
| `history_reflow_travel_pilot` | 1 | rewritten | `tests/textual/test_reflow_is_not_reader_travel.py` | Layer textual. Kept: trim compensation and resize clamps change scroll_y only while restoring, are not travel samples, anchor row held, scroll_revision unchanged, demand object unchanged, a key is sampled. |
| `history_scroll_frames_pilot` | 1 | rewritten | `tests/textual/test_history_scroll_frames.py` | Transcript and channel paging both hold the reader's row: the channel is drawn by the same line history (defect channel-reader-row-on-prepend closed). The slow-refresh case holds Core's page read instead of a widget method. |
| `image_attachment_inputs` | 1 | rewritten | `tests/model/test_image_inputs.py` | Model layer, five tests. build() now returns ACP schema blocks, so content[0].text / block.type / block.data replace dict access. Environment changes use monkeypatch. |
| `image_paste_pilot` | 1 | rewritten | `tests/app/test_image_paste.py`, `tests/textual/test_text_paste.py` | Split: image capture (app layer, via ui.press ctrl+v; the clipboard reader is patched) and the text fallback (Textual layer). The text fallback used to patch pyperclip.paste, which the clipboard transport chosen at startup no longer reads; |
| `in_out_underfill_pilot` | 1 | open defect | `tests/textual/test_filtered_history_underfill.py` | Three cases pass; re-applying a filter is intermittent open defect filter-reapplied-finds-nothing. |
| `independent_native_writer_pty` | 1 | deleted | — | Launched a script deleted earlier; only wrote records. |
| `initial_session_title_pilot` | 1 | open defect | `tests/textual/test_initial_session_title.py` | Four cases pass; three are open defect session-title-precedence. |
| `input_failure_pilot` | 1 | rewritten | `tests/textual/test_input_failure_draft.py` | three tests over detached agents and the submissions owner. |
| `input_latency_pilot` | 1 | rewritten | `tests/app/test_submissions_in_a_row.py` | with a real echo peer: 20 submissions and then typed keys reach the agent in order. The old test captured submissions in shell mode with post_message patched; submissions now require a ready agent. |
| `irc_wrap_pilot` | 1 | rewritten | `tests/textual/test_wire_message_lines.py` | Channel messages are lines, not widgets: wrapping on words at three widths, clickable names, and which rows count as reading. Dropped: Enter/Shift+Enter opening sender and destination of a focused row and per-row select-all (rows are no longer focusable widgets). |
| `l0a_archive_history_pilot` | 1 | rewritten | `tests/textual/test_archive_from_thread_menu.py` | textual; no native package. The menu is opened from the thread's sidebar row (sidebar._show_thread_menu no longer exists). |
| `l0a_native_installed_pilot` | 1 | rewritten | `tests/support/native.py`, `tests/support/native_steps.py`, `tests/native/test_native_journey.py` | The 716-line fixture is now support/native.py (controlled provider, private native wire, attached session) and the journey is eight tests. |
| `large_stream_pilot` | 1 | rewritten | `tests/model/test_terminal_state_stream.py`, `tests/textual/test_growing_answer.py` | Split: ANSI stream bounds (model, one run instead of three timed runs) and growing table answer / streaming-while-typing-and-resizing (textual). response.append became append_fragment; |
| `late_native_after_join_pilot` | 1 | rewritten | `tests/textual/test_late_live_answer.py` | textual (no native package needed); case 'read-in-flight'. Fails without the saved-history fix, passes with it. |
| `late_native_application_pilot` | 1 | rewritten | `tests/textual/test_late_live_answer.py` | textual; cases 'checkpoint', 'snapshot', 'queued-snapshot' (the old LATE_NATIVE_CASE variable). INTERMITTENT: [queued-snapshot] failed 3 of about 22 runs (twice two copies on screen 0.5 s after the answer was applied, once one frame with two copies); |
| `layout_alignment_pilot` | 1 | rewritten | `tests/textual/test_layout_alignment.py` | MainScreen is now the one WorkspaceScreen; the second session is ui.new_session, the right sidebar is read from the selected session. Dropped the trailing worker-cancel check (shutdown hygiene, no behaviour); |
| `lazy_tools_pilot` | 1 | rewritten | `tests/textual/test_lazy_tool_output.py` | ToolCall built from a ToolCallStatus (new step tool_status in tests/support/textual_steps.py); |
| `local_echo_pilot` | 1 | rewritten | `tests/textual/test_local_echo.py` | (needs the history writer patched and UserInput blocks). Uses an echo peer so the submission is accepted. |
| `markdown_token_rules_installed_pilot` | 1 | open defect | `tests/app/test_markdown_file_links.py` | Rewritten at the app layer; fails on open defect agent-text-click (no links in drawn agent text). |
| `mcp_decision_pty_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_mcp_inventory.py`, `tests/support/native_mcp.py` | two tests (inventory decoding, decisions through the terminal dialog). |
| `message_filter_supersession_pilot` | 1 | rewritten | `tests/textual/test_message_filter_late_page.py` | fragment_views became fragments_in_range, the polling loop became ui.until. |
| `message_notifications_pilot` | 1 | rewritten | `tests/textual/test_message_notifications.py`, `tests/textual/test_message_notification_title.py` | The notification state is a line under each message (title, details on click), asserted on screen. Feedback follows the next observed change (the observation timer is gone); a view stops reading when another tab is selected. The ObservedThreadActivity section tested removed methods. |
| `model_picker_pilot` | 1 | open defect | `tests/textual/test_model_picker.py` | Six cases pass; two are open defect model-picker-highlight. |
| `native_message_parts_pilot` | 1 | rewritten | `tests/app/test_native_message_parts.py` | Agent text is line-drawn, so MarkdownFence/MarkdownBulletList and AgentResponse.source are replaced by visible lines: one Agent divider, heading 'Plan', bullets, code line, no raw ``` or ** left. The journal is written through support.journals. |
| `native_tab_terminal_check` | 1 | not converted | — | Needs the st terminal, xdotool, python-xlib and Pillow; see "What the suite does not cover". |
| `native_tool_output_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_tool_output.py` | Same assertions. |
| `native_widget_actions_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_widget_actions.py` | two tests. The context-disclosure expand/collapse section is gone with its widget: coordination context is a one-line summary in the line view (expansion is a listed gap in docs/agents/DECISIONS.md). |
| `navigation_resource_lifetime_pilot` | 1 | rewritten | `tests/textual/test_hidden_session_retirement.py` | four tests. Work counts kept (zero Comms constructions, registry decodes, action discovery, option rebuilds; hidden vs selected prompt), elapsed-time output dropped. registry.delete_originals is now remove_originals. |
| `offscreen_tool_hydration_pilot` | 1 | rewritten | `tests/textual/test_offscreen_tool_diff.py` | kept the not-yet-mounted-then-hydrated-on-scroll assertions. Dropped the TOAD_BENCH_EAGER_TOOLS environment switch variant (a benchmark mode that patched _visible_in_window) and the printed millisecond figures. |
| `owner_navigation_pilot` | 1 | open defect | `tests/app/test_channel_tab_sharing.py` | A channel has one tab for all sessions (deliberate). What the tab does for a second session is open defect shared-channel-tab. |
| `owner_poll_latency_pilot` | 1 | deleted | — | Only printed timings. |
| `owner_reader_reuse_pilot` | 1 | rewritten | `tests/app/test_owner_reader_reuse.py` | (workspace fixture, one test also starts the app). Three tests: shared reader and root change, replaced owner receives no request, bound reader is the app's own service. Uses support.agents.detached and support.coordination.registered_coordination_fact. |
| `path_filter_pilot` | 1 | rewritten | `tests/model/test_path_filter.py`, `tests/textual/test_path_filter_tree.py` | PathFilter assertions go to model; tree root change and hidden-session deferred reload go to Textual. Hidden session publishes on the MainScreen captured as app.selected_session (WorkspaceScreen has no publish_core); return is ui.select_tab. |
| `pending_thread_open_pilot` | 1 | rewritten (needs native package) | `tests/native/test_thread_open_during_slow_load.py`, `tests/support/peers/delayed_load.py`, `tests/native/test_native_journey.py::test_a_second_thread_opened_from_the_app_answers_its_first_message` | The scripted peer (was acp_navigation_server.py) claims a Core thread but publishes no input queue; |
| `permission_pending_mount_pilot` | 1 | rewritten | `tests/textual/test_permission_requests.py`, `tests/app/test_permission_across_tabs.py` | The hand-rebinding cases are replaced by app tests through a real scripted agent and real tab switches; all pass. |
| `persistent_workspace_source_navigation_pilot` | 1 | open defect | `tests/textual/test_source_link_navigation.py` | Open defect agent-text-click. |
| `project_resume_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_project_resume.py` | plus test_a_project_change_reported_by_the_agent_moves_the_session. Found: ContextInspection.same_native_source read Thread.publication_identity, removed from Core (the integration branch carries the fix). |
| `projected_history_budget_pilot` | 1 | rewritten | `tests/textual/test_projected_history_budget.py` | Layer textual (the budget validation test is in the same file). fragment_views replaced by overlay.fragments_in_range. Dropped: selected paragraph surviving four admissions and materialized widget peak. |
| `prompt_completion_installed_pilot` | 1 | fixed + open defect | `tests/textual/test_prompt_completion.py`, `tests/app/test_local_command_before_agent_ready.py` | Product: a command advertised with an input hint made Toad exit (fixed in slash_command.py). The hint refresh is open defect command-hint-refresh. |
| `prompt_popup_new_case_pilot` | 1 | rewritten | `tests/textual/test_prompt_popup_declaration.py` | two tests. Plumbing: the declared popup must now implement compose_content (abstract) rather than compose, and its content is built on first focus, so the test waits for the Input to exist and take focus. |
| `prompt_routing_pilot` | 1 | rewritten | `tests/app/test_prompt_routing.py`, `tests/textual/test_prompt_shell_mode.py` | Typed with no agent attached, so nothing was submitted; uses a scripted agent and reads what it received. |
| `queue_admission_pilot` | 1 | not converted | — | Holding a native turn so the queue fills needs a Core mechanism the old test did not name; see "What the suite does not cover". |
| `quit_save_installed_pilot` | 1 | rewritten | `tests/textual/test_quit_with_unsaved_settings.py` | peer("completion"); error toast enabled with record_notifications; asserts the same failure-visible, draft-retained, retry-saves-137-and-exits, no input replay. |
| `reader_geometry_pilot` | 1 | rewritten | `tests/textual/test_reader_geometry.py` | Layer textual. Fixture admits every fragment at once (PresentationBudget batch_items 240) because lazy admission makes the old heights unstable; PageDown is pressed until the bottom (older fragments are admitted on the way). |
| `reconnect_source_native_installed_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_reconnect_history.py` | Counts drawn answers and saved events; the count of AgentResponse widgets is dropped because saved history is drawn as lines. |
| `resize_pty` | 1 | rewritten (needs native package) | `tests/terminal/test_resize.py` | Needs pyte and a native package. |
| `retained_history_projection_pilot` | 1 | rewritten | `tests/textual/test_saved_history_coverage.py` | Layer textual. Journal written with support.journals; agent via agents.detached. Dropped: waiting for a nested rendering pager in a long live message (agent text is line-drawn); the live-message-is-not-coverage assertion kept without it. |
| `retained_input_origin_native_pilot` | 1 | rewritten (needs native package) | `tests/native/test_native_human_input_origin.py` | Same assertions. |
| `retained_page_end_pilot` | 1 | deleted | — | Tested page widgets' fragment_views and document_viewport, which no longer exist. |
| `right_comms_integration_pilot` | 1 | fixed + open defect | `tests/textual/test_thread_relationship_sidebar.py` | Product: Toad read Thread.publication_identity, which Core removed (fixed in core/context_inspection.py). Still fails on open defect relationships-revision. |
| `selection_hover_pilot` | 1 | rewritten | `tests/textual/test_hover_during_drag.py` | MarkdownParagraph became response.body. |
| `session_details_pilot` | 1 | rewritten | `tests/textual/test_session_details.py` | The collapsed summary also names the latest inbound message now, so the test uses a screen wide enough to show all of it. |
| `session_initial_prompt_custody_pilot` | 1 | rewritten | `tests/textual/test_initial_prompt_handoff.py` | two tests (constructor transfer; publish once across eviction and remount with draft and undo kept, consumed prompt not restored, close releases state). Dropped the receipt file and cleanup prints. |
| `session_route_installed_pilot` | 1 | deleted | — | Core holds the default route while a client is attached, so the route cannot change under a running Toad; the scenario cannot occur. |
| `sidebar_direction_pilot` | 1 | rewritten | `tests/textual/test_sidebar_direction.py` | The old first failure was plumbing: button.action is now an action object, so arrows() filters on action.directional instead of != 'float'; with that all arrow assertions pass unchanged. |
| `sidebar_navigation_pilot` | 1 | rewritten | `tests/textual/test_sidebar_state_across_views.py` | Opening a row makes it the range anchor and does not select it. The hidden-sidebar case went: the channels sidebar is one shared widget. |
| `sidebar_projection_pilot` | 1 | rewritten | `tests/textual/test_sidebar_projection.py` | One channels sidebar is shared by all views now, so the per-mode sidebars became the one shared sidebar plus each view's own thread sidebar; frames use selected_mode instead of current_mode. |
| `sidebar_retirement_pilot` | 1 | fixed + open defect | `tests/textual/test_sidebar_retirement.py` | Three cases pass after the publication_identity fix; the fourth is open defect relationships-revision. |
| `snapshot_cancellation_custody_pilot` | 1 | rewritten | `tests/textual/test_snapshot_cancellation.py` | The checkpoint case built a second checkpoint by hand, which lost a race to the transcript owner's own and returned without doing anything; it now cancels the owner's checkpoint. Same four requirements. |
| `source_admission_trace_pilot` | 1 | deleted | — | Only wrote a record file. |
| `stale_selection_pilot` | 1 | rewritten | `tests/textual/test_stale_diff_selection.py` | PatchDiffView is not a ConversationBlock so the diff is mounted inside an edit ToolCall. |
| `stepped_layout_restoration_pilot` | 1 | rewritten | `tests/textual/test_stepped_layout_restoration.py` | Textual's stepped layout commits the arrangement at one step and renders after it; the test asserts that contract. |
| `stream_style_work_pilot` | 1 | rewritten | `tests/textual/test_old_output_is_not_restyled.py` | kept zero-restyle counts for append and sidebar toggle; dropped printed millisecond figures. |
| `t8_mounted_pilot` | 1 | rewritten | `tests/textual/test_command_pane_and_resume_modal.py`, `tests/model/test_saved_sessions_of_this_machine_read_back_typed.py` | Command pane environment and resume modal to Textual (bare App now ThemedApp, saved AgentDefinition has a name). The read-only check of this machine's ~/.local/state/toad/toad.db is its own model test and skips when absent; |
| `tab_order_pilot` | 1 | rewritten | `tests/app/test_tab_order.py` | Selected sessions through Textual's switch_mode; asks the harness now. |
| `terminal_crash_pilot` | 1 | rewritten (needs a terminal emulator) | `tests/terminal/test_terminal_crash.py`, `tests/support/terminal_crash_app.py` | Real PTY via support.terminal; script app moved into support; asserts exit 1, one 0600 Terminal_crash file naming fail_after_paint, no locals, error echoed on the terminal. |
| `test_agent_configuration` | 1 | rewritten | `tests/model/test_agent_configuration.py` | Model layer; the fake that collected post_message is a detached Agent whose events stream is subscribed (ConfigurationChanged from the agent is the old 'message.agent is agent'). |
| `test_fixture_journal_retention` | 13 | deleted | — | 13 tests of a cold-storage utility for record files that nothing used. |
| `test_shared_acp_transport` | 2 | rewritten | `tests/model/test_sessions_share_one_stdio_process.py`, `tests/textual/test_workspace_tabs_share_one_agent_connection.py`, `tests/support/shared_stdio.py` | Split into the Agent-objects test (model) and the two-tab app test (textual). claim_thread lost start_at_latest (inbox now starts at creation), dropped. The app test needs AGENT_COMMS_AGENT_MODELS=test/one via monkeypatch for the model catalogue. |
| `test_sidebar_destinations` | 1 | rewritten | `tests/textual/test_sidebar_destinations.py`, `tests/guards/test_sidebar_row_dispatch.py` | Bare App mixes in ThemedApp; no separate busy-label timer is required. The AST guard moved to guards. |
| `test_sidebar_rows_in_steps` | 1 | rewritten | `tests/textual/test_sidebar_rows_in_steps.py` | moved; bare App mixes in ThemedApp. Flaky as found: test_short_list_mounts_at_once failed 2 of 5 runs alone and 2 of 5 runs with -n 2 (rows mount against a wall-clock step budget, Screen.LAYOUT_STEP_NS = 4 ms, exceeded under nice). |
| `test_t8_boundaries` | 1 | rewritten | `tests/model/test_saved_sessions_database.py`, `tests/model/test_danger_spans.py`, `tests/guards/test_session_rows_and_danger_dispatch_stay_typed.py` | Three files. Saved agent_data in the test row now carries a name and the SessionMeta uses an AgentDefinition (AgentDefinition requires name; the old dict was not a valid definition). |
| `test_tool_output_acquisition` | 1 | deleted | — | Asserted on per-fragment history widgets (fragment_views), which no longer exist; tool output in history is a line summary. |
| `thread_activation_pilot` | 1 | rewritten | `tests/textual/test_thread_activation.py` | four tests. response.append became append_fragment; TranscriptCursor/Page imported from agent_comms.transcripts; the snapshot test needs a detached agent attached (otherwise the snapshot is never published). |
| `thread_render_wait_pilot` | 1 | rewritten | `tests/textual/test_replay_preparation_does_not_block.py` | The leave-and-return case was removed: its fixture delivered the saved page once, while the product reads it again on attach. |
| `tool_diff_lifecycle_pilot` | 1 | rewritten | `tests/textual/test_tool_diff_lifecycle.py` | split into three tests (hidden preparation then reveal; replace/theme/collapse/remount/remove; remount while hidden and cancelled worker). The installed stylesheet is now ToadApp's default, so the CSS_PATH subclass was dropped. |
| `tool_read_latency_pilot` | 1 | rewritten | `tests/textual/test_read_tool_selection.py` | kept the exact full-source selection assertion for two samples; dropped the ready/CPU/event-loop-gap measurements (printed, never asserted). |
| `transcript_lifecycle_pilot` | 1 | rewritten | `tests/textual/test_transcript_lifecycle.py`, `tests/guards/test_transcript_history_has_no_lifecycle_flags.py` | Layer textual; the AST check that the history widget uses no _committed/_closing/_pruning moved to a guard. Journal written through support.journals. |
| `transcript_source_lifetime_pilot` | 1 | rewritten | `tests/textual/test_page_read_against_changed_source.py` | Layer textual. Five causes (current, revision, edge, parked, loader) as parametrized tests plus the requested-page worker test. |
| `typed_comms_command_pilot` | 1 | fixed | `tests/textual/test_compaction_turn_events.py` | Product: Toad read CompactionPhase.started_at, which Core removed; the turn status raised during compaction. Fixed in conversation_turn.py. Compaction has a start and an end and no source progress now. |
| `unread_navigation_pilot` | 1 | rewritten | `tests/app/test_unread_clears_on_opening.py` | three tests (channel incl. return to open tab, direct messages, #any feed). Actor is workspace.viewer; the badge is read from the tab title (no '(1)') instead of the OpenTab unread value; chat rows read via ui.until_shows. Added Ui.open_direct. |
| `viewport_bounded_runway_churn_pilot` | 1 | deleted | — | Tested body eviction and warm bodies of the deleted per-message widgets. |
| `viewport_demand_custody_pilot` | 1 | rewritten | `tests/textual/test_scroll_reversal_revokes_preparation.py` | Layer textual. The held body restoration (manager._restore_bodies, body_roots, retire_body, suspend_source: gone) is dropped; kept: forward travel demand, PageUp reverses it, the outgoing demand is no longer accepted by window.lookahead. |
| `viewport_layout_reentry_pilot` | 1 | rewritten | `tests/textual/test_reader_position_in_live_output.py` | Layer textual. Dropped the nested-layout count during presentation.prepare (viewport_presentation gone); kept tail follow through growth and resize, reading position held, output painted, session switch and return. |
| `viewport_rapid_scroll_pilot` | 1 | rewritten | `tests/textual/test_rapid_paging.py` | Layer textual. Kept PageDown/End rounds reaching the painted tail, no frame with scroll_y > max, draft and undo history untouched. Dropped body_ready/dormant checks, idle CPU/RSS print and preparation caps (those were of per-message bodies). |
| `viewport_runway_pilot` | 1 | rewritten | `tests/textual/test_history_runway.py` | Layer textual. Kept the history_buffer_viewports setting reaching the window lookahead and restoring, held PageUp/PageDown never drawing an empty message area, End following the tail. |
| `viewport_selection_diff_pilot` | 1 | rewritten | `tests/textual/test_selection_across_clipped_diff.py` | MarkdownParagraph lookups became the AgentResponse body widgets (answers are one LineMarkdown now); all assertions kept. |
| `welcome_source_return_pilot` | 1 | deleted | — | Assumed one conversation widget rebinding to a new source; each session has its own now. |
| `worker_native_size_pilot` | 1 | deleted | — | Mixed the deleted body-retirement machinery with private WorkerStatic fields. WorkerStatic has no direct test now (see "What the suite does not cover"). |
| `worker_preview_pilot` | 1 | deleted | — | Injected a renderer through ToadApp(renderer=), which no longer exists, and asserted private WorkerStatic fields. |
| `workspace_native_paint_retention_pilot` | 1 | rewritten | `tests/textual/test_tab_return_keeps_blocks.py` | Layer textual. Kept same conversation, same response children and draft after tab A/B/A. Not carried over: identity of MarkdownParagraph strip caches, invalidation by response.update/resize (MarkdownParagraph widgets and AgentResponse.update do not exist; |

