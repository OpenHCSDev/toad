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
Combined installed application measurement and frontend delivery are pending.
Backend startup remains a separate unresolved cost.
