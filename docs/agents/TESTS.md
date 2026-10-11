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
| `tests/textual` | Behaviour owned by the Textual frontend: paint, layout, strips, compositor, widget classes. The module docstring starts with `Textual-facing:` and says what Textual owns here | everything, through `ui.textual` |
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

On this machine prefix runs with `taskset -c 0-5 nice -n 19` and use at most 6 workers. A failing app test prints the screen it last saw and keeps its roots under `/var/tmp/toad-test-*`.

## Resolution of the failing ids

Filled in as each batch lands.
