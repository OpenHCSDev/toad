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

Result:20 physical tab clicks completed in each run, alternating the completed
p35 saved conversation and the real #any view. Every baseline switch called
sidebar paint_current27 times; every final switch called it2 times (540→40).
The relationship tree had no current rows in this journey and made0 calls.
This is a call-count result, not a claim of7ms frames or a default installation.

The first candidate exposed stale emphasis because refresh_paint only invalidates
changed native paint keys; render-derived current emphasis was outside that key.
ViewLabel now explicitly refreshes the two invalidated resources. Repeated the
20-click run and inspected both the screenshot and retained native strips:
selected comms tab bold/underlined=True, departing saved tab=False. Raw earlier
candidate failures are retained, not substituted for the accepted run.

Final private acceptance: after-paint/{20-switches.json,scene.json,20-switches.png}.
Baseline: before-start/{transitions.jsonl,20-switches-offset.json,20-switches.png}.
Startup provenance confirms private HOME and observed wire, normal plain st,
installed T134212Z dependencies with the candidate Toad source overlay.
Only completed p35 SDK history is opened; other original source names are a
fresh private roster without source SDK pointers, pending inputs or goals.
The loaned P21 root and original saved file are untouched. No provider input.

AST owner/consumer census:282 Toad modules and254 installed Textual modules,
zero parse omissions. Native current-row paint now has one declaration owner,
ViewLabel; row and tab subclasses derive its current answer. All sidebar
sync_current consumers and changed-row paint lists are deleted. No tests added
or run. Existing lint findings compare identically against main; functional
import/whitespace checks pass, debt ratchet introduces0. Integrated current main
normally before the final accepted UI run. Source9 files +62/−67, net−5.
