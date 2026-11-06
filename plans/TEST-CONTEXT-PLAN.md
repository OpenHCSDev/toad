# One booted Toad per test worker, a fresh workspace context per test

## Why

A small app test costs about 0.9 s, and about 0.05 s of that is the test. The rest is Toad
booting: about 300 widgets composed and styled, the conversation mounted, the route observer and
render workers forked (measured 2026-11-06 with timestamps along one test's path and cProfile of
the boot). 594 app tests boot 594 Toads, which is about half of a serial `tests/textual` run.

Caching between tests does not fix it, because the cost is per app instance. Booting one Toad in
the test template before forking moved small tests from 0.93–1.04 s to 0.88–0.95 s. Sharing parsed
CSS and rule matches across every stylesheet in the process moved them nowhere. Both were dropped.

Others solve it the way Playwright does: one browser per worker, and a fresh *context* per test.
Toad's browser is the app shell (screen, stylesheet, colours, render pool). Its context is what
one launch binds today: the project, the Core connection, the settings, the tabs.

## What one launch binds today (ToadApp.__init__ and its owners)

| bound at construction | owner | per-test today because |
|---|---|---|
| `project_dir` | `ToadApp.__init__` (app.py:154) | the test's project checkout |
| `coordination_access` | `connection.open_access(self)` (app.py:196) | the test's own bus root |
| `tab_order` (its DB and scopes) | `TabOrder(..., db=DB(), scopes=connection.tab_scopes())` (app.py:189) | the test's state directory |
| `saved_settings` | `TextualColours.__init__` → `open_settings` (textual_colours.py:525) | the test's config directory |
| `agent_binding`, `application` (resumed session) | `ToadApp.__init__` | per launch |
| `session_navigation`, `thread_navigation`, `thread_actions`, `sidebar_state`, `_session_tracker` | `ToadApp.__init__` | in-memory state of one launch |
| `LaunchRoot._current` | `Workspace.__init__` → `launch_root.install()` (agent_comms/launch_root.py) | process-wide; `selected()` already scopes it |

Already per call, and so already context-correct: `paths.get_config/get_data/get_state` read the
XDG variables on every call (paths.py:26-48); `DB.path` reads `paths.get_state()` per call (db.py:44).

Shared by every context: the workspace screen and its chrome, the stylesheet, colours and theme,
the render process pool (data-only functions), the preparation runtime.

## The change

1. **`WorkspaceContext`**: one object holding every row of the table above. `ToadApp` holds the
   current one and asks it; nothing in the table stays a direct `ToadApp` attribute. Opening the
   app builds the first context from the launch, as today.
2. **Switching context**: `ToadApp.open_context(context)` retires the open tabs and their session
   screens, closes the old `coordination_access`, selects the new launch root, opens the new access,
   loads its tab order and settings, and selects its home. This is also the product feature of
   opening another project or root without restarting Toad.
3. **The test runner**: app tests run in one long-lived process per xdist worker that boots Toad
   once. Per test: create `Roots`, set its environment, `open_context` on it, run the body, close
   the context, and fail the test if a task, child process or subscription from it is left over.
   That leftover check replaces the isolation the fork gave.
4. **Delete** what the per-test fork existed for: `OwnProcessTest`, the template's per-test fork and
   the warm helper spawner, except for cases that assert on a fresh interpreter
   (`tests/support/keymap_discovery.py` keeps its own `python -m`).

## Done when

- `tests/textual` serial time drops by at least the boot share (about half), measured on the same
  machine and env as the 2026-11-06 numbers (8 workers: 206 s).
- Every app test passes in the shared runner with the leftover check on; any test that leaks state
  is fixed at the leak, not excluded.
- Opening another project in a running Toad works from the UI.
