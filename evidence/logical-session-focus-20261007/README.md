# Logical session focus

The agent-tab profile recorded 20–25 native arrangements during a switch,
including the hide handler's fallback focus search. The departing logical
source already owns retirement. It now releases focus belonging to its own
subtree before hiding; focus in shared chrome remains untouched. Destination
selection retains its original autofocus decision. Closing a selected tab
already selects the surviving source before removing the departing view.

Prompt.focus now forwards the original scroll_visible argument to its owned
editor or question, rather than silently requesting a scroll during destination
focus. ChannelPrompt's editor remains supplied by its existing subclass.

The actual editor click/traversal/typing/Undo/return workflow passed, including
focus release on parking and restoration on return. NRA's original parser
covered 288 source, 406 test and 40 tool modules without omissions. Native PR91
separately makes is_on_screen read committed geometry rather than acquiring a
new layout for a status query; explicit geometry demands retain that behavior.

Original editor artifacts:
`/home/ts/.cache/agent-scratch/logical-session-focus-20261007`.
Original opening profile:
`/home/ts/.cache/agent-scratch/agent-screen-mount-cpu-live-20261007`.
The combined installed open/close/reopen journey passed all six checks, with
original source and runtime unchanged, no cleanup errors and no owned processes
left behind. Recorded arrangements fell from 25/20 during open/reopen to 15/13.
Opening measured 492 ms, return 159 ms, reopening 331 ms; the earlier profiled
run measured 504/167/457 ms. These are single-run elapsed observations with
different profiler overhead, not a reliable speedup or input-to-pixel claim.
ACP initialization remains 2.03/1.88 seconds and is independently unresolved.

Combined candidate artifacts:
`/home/ts/.cache/agent-scratch/session-focus-candidate-installed-20261007`.
All 953 installed assets matched Git/wheels, all 69 versions matched and 2,787
hashed RECORD entries matched. Frontend publication and actual-default check
completed through the existing frontend owner. PR515 and native PR91 merged.
The actual default-launch journey also passed all six checks with original
source/runtime unchanged and owned cleanup complete. Screen switching measured
363 ms on open, 170 ms on return and 328 ms on reopen; backend initialization
still measured 1.89/2.04 seconds. This confirms working delivered behavior at
that scope, not that whole agent opening is fast. Existing backend processes
and older windows are preserved.

Actual-default artifacts:
`/home/ts/.cache/agent-scratch/session-focus-default-live-20261007`.
The initial publisher refusal was an output-directory permission check before
any publication. The owned directory was corrected and publication completed
once; no application attempt was repeated.
