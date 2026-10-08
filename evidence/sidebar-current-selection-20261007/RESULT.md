# Shared sidebar selection and visible message dates

The selected logical SessionView owns its displayed destination. MainScreen
supplies its original published thread; CommsScreen supplies its original target.
TargetTree consumes that declaration and the original wire binding for every
row, in both sidebars. It no longer identifies a concrete CommsScreen or caches
another painted-mode answer. New row admission updates the same current state.

TargetTree now owns the existing range/toggle algorithm. Channels retains its
original `(channel, target)` selection and disclosure/restoration rules; the
right tree retains independent `(relationship group, target)` identities and
owner/root-scoped view state. Primary navigation retains the range anchor and
clears bulk selection. Hover and keyboard focus remain native pseudo-classes.
CommsRow owns the row styling: current is bold, bulk selection has a background,
hover/focus is underlined, and combined states preserve both meanings. The
competing tree-wide bright/inverted rule and unused selected-target mirrors were
deleted.

RelationshipRow explicitly invoked its base click handler even though Textual
already traverses the MRO for native event delivery. Ctrl toggled twice. The
extra super call is deleted; native dispatch supplies the base handler once.
No new event queue, copied navigation state or backend command decision exists.

MessageClock already owns local timestamp formatting. Its visible label now
includes ISO date and time; the existing tooltip also retains the timezone.

## Verification

The reusable refactor-audit Package parsed the original source (288 modules),
tests (414) and tools (40), without omissions. Its declaration and consumer
trace is retained in `/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/sidebar-state-before.txt`.
Related callers are migrated in the same source change. Dynamic third-party
mutation remains outside this static evidence.

One actual private-store native App check passes in both normal and ANSI themes:
channel active styling agrees in the left roster and right outbound relation;
Ctrl/Shift does not navigate; plain navigation clears bulk paint; right Ctrl
toggles once; hover retains active bold; returning to the agent selects its
original thread; the native divider displays the recorded date. Provider inputs
are zero and the fixture/App children are joined. Earlier negatives are retained:
newly disclosed rows originally missed current paint, and right Ctrl double
toggled through the explicit super call. Logs are in the same scratch directory.

Installed verification and publication follow this coherent checkpoint. This
change makes no frame-pacing or busy-channel latency claim.
