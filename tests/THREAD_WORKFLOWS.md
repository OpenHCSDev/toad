# Local verification

Install the committed dependency pins with `uv sync --locked --all-extras --no-editable`, then run
`.venv/bin/pytest`. The collector derives script pilots from `tests/`;
normal pytest tests and architecture guards are collected alongside them.
Use pytest selection (`-k`, a path, or `--collect-only`) rather than a manual roster.

Each pilot gets an isolated subprocess and private state/cache/temp roots. The
existing Comms child owners bound runtime and retire only processes carrying
that attempt's private identity, including workers that detached from the UI. A timeout is a failure, never a retry or skip.
`--pilot-timeout` adjusts the one-attempt budget. Logs remain in pytest's fixture
root for failures; use a persistent `--basetemp` under your worktree.

Test changes to Comms through the paired committed dependency pin, not an
editable shared checkout. CI is deferred and no merge gates are enabled.
Performance investigations live under `tools/performance/`, outside collection.

Native route pilots require `AC_NATIVE_COPIED_PACKAGE` pointing to the package
validated by the pinned Comms native builder. Reuse an existing prepared package
locally; the manual workflow invokes that owner on the exact Comms pin. A wrong
package fails verification before execution. No real provider credentials are
needed: the native model fixture binds only loopback. After source changes, build
and reinstall the local Toad wheel before claiming installed-source acceptance.

The real pixel pilot also requires `st`, `Xvfb`, and `xdotool` on PATH; its Python dependencies are in the dev group. The saved settings pilot defaults to the representative saved document under `tests/fixtures`; set `TOAD_SETTINGS_SAMPLE` to test an explicit saved file without changing it.
