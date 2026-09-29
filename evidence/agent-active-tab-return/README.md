# Active agent tab return: paired runtime reproducer

Owner: agent tab presentation. Base: merged `#191` (`4da12b5a`).

The paired isolated installed run used Toad `00d2f03f`, agent-comms Core
`64db`, and Textual `609b`. Its `tests/native_loaded_return_cache_pilot.py`
recorded five ready-tab A/B/A first frames with the saved reader, goal,
status, turn, scroll, and editor assertions passing. On the next click to
Gamma while a native turn was active, the first selected frame had a blank
reader. The held native turn and Gamma draft were still present. The reader
assertion at line 243 failed.

Original log (preserved outside this branch):
`/home/ts/.cache/agent-scratch/live-pair-20260929/native-return.log`, lines
255–288. The failing fixture invocation is in the paired installed stack;
this checkpoint records the external failure, not a local reproduction yet.

Acceptance: run the same continuous native saved-state A/B/A and active-turn
clicks through an isolated installed Toad wheel, real Textual UI and ACP/Pi
process, and loopback provider. The first Gamma reader paint must contain its
saved reader or current native prompt, with Gamma status, turn, and goal;
ready returns must continue to preserve reader, scroll, draft, undo, and
retained bodies. Record return latency and clean owned scratch afterward.

Scope: session presentation, conversation, and existing presentation/viewport
owners only. Sidebar/workspace work belongs to `#185`; `#116` is obsolete.

## Resolution and installed acceptance

The apparent blank *first painted* Gamma frame was a recorder error. Textual's
`App._display` returns without displaying when `_batch_count` is nonzero.
`PaintedReturnApp._display` nevertheless recorded those calls. In a diagnostic
run the early blank captures had no mounted history; later captures in that
same click had Gamma history and content. The corrected recorder filters the
discarded batch frames. No production source change was warranted by this
paired-stack failure; the merged `#191` presentation passed the observable
first-frame assertion on the affected stack.

Isolated installed-wheel run: Toad source `4da12b5a` plus this test change,
agent-comms `64db0f664774a9230ae4b260fc0d76814f0e9468`, Textual
`609b74bf3d7851bd2c1eff61dc2790e86e1925af`, copied native package
`native-current-9213ee71479d1b20`, real Textual app/tab clicks and ACP/Pi
owner processes, loopback provider. Toad was imported from the isolated
`.venv` wheel in `site-packages`. The continuous pilot passed five ready
A/B/A returns with exact reader paint and scroll, draft/undo, status, turn,
goal, retained response body, bounded cache, and no provider replay. Its held
active Gamma return passed first eligible frame reader/goal/status/turn and
settled after one additional provider request.

Ready click completion times: 688.8, 634.2, 670.4, 599.2, 586.0 ms.
Active Gamma click completion: 750.7 ms. These are click-to-pilot-return
wall times, not driver write timestamps. Five ready returns each reused one
visible response body with three cache hits and zero misses.

Focused session observation ownership/retirement checks passed directly.
Pytest collection with Core `64db` is blocked by an existing `conftest.py`
import of removed `DetachedProcess`; the older transcript-publication guard
also calls absent `WorkspaceScreen.wait_content_ready`. Neither affects this
continuous installed pilot. No live user installation was changed.
