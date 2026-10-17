# P171: derive current paint, invalidate changed destinations

Owner core-read-locks. Source baseline Toad8837f46e2; isolated checkout
/home/ts/wt/toad-sidebar-current. No tests or saved-input replay.

WorkspaceSessions owns the visible destination. SessionSelected carries the
original transition's prior mode, not a widget's remembered current row.
TargetTree derives row_current and resolves old/new destinations through its
existing group row dictionaries. Both group families key native rows by the
canonical target name; relationship selection retains the original full entry
identity for revalidation. Hidden mounted rows also receive invalidation.
ViewLabel paints current emphasis when rendered, never into semantic content.

Remove all sidebar sync_current calls and their changed-row lists. Normal label
updates/mounts paint themselves; only SessionSelected invalidates old/new targets.
The shared ViewLabel consumer SessionLabel likewise derives its current answer.

Acceptance: private plain st, completed p35 saved-session fork,20 actual tab
switches before/after, count sidebar paint_current calls from selection events.
No provider input, uncertain replay or borrowed-root activation. Scratch/evidence:
/home/ts/.cache/agent-scratch/p171-core-read-locks.
