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
