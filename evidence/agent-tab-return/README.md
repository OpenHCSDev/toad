# Native agent tab return checkpoint

Branch `fix/agent-tab-warm-return-20260929` began at OpenHCSDev/toad
`bc503af8`. PR #191 owns only `session_presentation.py`,
`widgets/conversation.py`, this evidence, and
`tests/native_loaded_return_cache_pilot.py`. PR #185 owns sidebar and workspace
files; its owner was notified of the exact boundary. #116 is obsolete.

## Reproducer and fix

The existing real ACP/Pi two-source pilot passed its eventual history assertions
on base `bc503af8`, but five A/B/A returns took 307–351 ms to paint the saved
reader. With physical tab clicks and capture of every compositor frame, its new
first-frame assertion failed: the first selected frame painted `ThreadLoading`,
then several frames had an empty reader. The shared `Conversation` reset its
source and removed its history on each return; transcript publication resumed
asynchronously after the mode-switch paint transaction ended.

The returning ready Agent now publishes its current saved page and goal within
that same atomic switch. The existing `DocumentViewport` shelf reuses rendered
response widgets and the existing preparation cache supplies page data. The
loading widget is removed before paint. The selected Agent supplies the status
line and turn activity; a queued status event reads the currently attached
Agent instead of copying its old payload. The initial welcome is emitted only
when an Agent actually starts in this Conversation.

## Acceptance

An isolated wheel built from PR head `d4a7efb4` was installed into this
worktree's own `.venv`; `toad`, `agent_comms`, and `textual` imported from that
environment's `site-packages`. The fixture verified the pinned copied Pi tree
`native-current-9213ee71479d1b20` and used a localhost model response. The
real `ToadApp.run_test` UI, compositor, physical tab clicks, ACP transport,
native Pi workers, owner process, and saved journals remained in use.

`tests/native_loaded_return_cache_pilot.py` PASS: two independently loaded
native sessions, five A/B/A physical returns, destination history and goal in
each first selected frame, no old goal/reader/loading widget, selected Agent
status and turn identity, same scroll position and exact settled reader paint,
same Document/EditHistory and undo, same Agent/process/runner, no replay. A held
Gamma native turn also returned with Gamma's goal and active turn. A deliberately
late status event did not replace Gamma's selected status. All five returns
reused a rendered response instance; three preparation hits per return, and
one of five returns had one miss. Prepared bytes remained below the existing
bound. Measured click-to-settled-return median was 597.9 ms, range 559.3–714.8
ms in this fixture. First-frame content is fixed; this is not a latency target
pass.

`WORKSPACE_COHORTS=4 tests/native_session_retention_pilot.py` PASS from the
same wheel: real ThreadTarget/open-tab path, one global rich Conversation,
two fixed native owners/ACP attachments, held-turn queue and answer, draft and
undo. Five loaded first paints were 101.7–133.9 ms in its smaller fixture.

Focused `send_status_pilot.py` and `goal_collapse_pilot.py` PASS. `git diff
--check` and compileall PASS. `blank_presentation_pilot.py` fails at its
distinct-shell-view assertion (`restored_shell_view is not shared_surface`);
the changed return path only runs for an attached ready Agent. This pilot is
not included in the acceptance claim. No full suite, live installation, or
terminal-emulator latency validation was run.

The disposable test directory was owned by this PR at
`/home/ts/.cache/agent-scratch/toad-tab-return-20260929` for native fixture
output and wheel staging. It was removed after these results were recorded.
