# Local verification

Install the committed dependency pins with `uv sync --locked --all-extras`, then run
`uv run --locked pytest`. The collector derives script pilots from `tests/`;
normal pytest tests and architecture guards are collected alongside them.
Use pytest selection (`-k`, a path, or `--collect-only`) rather than a manual roster.

Each pilot gets an isolated subprocess and private state/cache/temp roots. The
existing Comms child owner bounds runtime and retires its namespace, including
workers that detached from the UI. A timeout is a failure, never a retry or skip.
`--pilot-timeout` adjusts the one-attempt budget. Logs remain in pytest's fixture
root for failures; use a persistent `--basetemp` under your worktree.

Test changes to Comms through the paired committed dependency pin, not an
editable shared checkout. CI is deferred and no merge gates are enabled.
Performance investigations live under `tools/performance/`, outside collection.
