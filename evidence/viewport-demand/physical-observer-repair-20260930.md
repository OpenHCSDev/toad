# Physical236 observer failure and repair

Protected failed raw run:
`/home/ts/.cache/agent-scratch/toad-workspace-warm-236-20260930/capture`.
The 78.013-second run completed its recorder processes, but did **not** perform
agent A/B/A or focused transcript scrolling. Its native review correctly records
`draft_typed=false` and `peer_selected=false`. No physical performance or buffer
acceptance follows from this run; there were zero native inputs and no UNKNOWN
inputs. Original video, phase screenshots/DTOs, driver log and receipts remain.

At warm-start Textual's partial `_visible_map` held111 entries. After draft the
partial map was None, while its committed `_full_map` held311 entries and frame
publication was Presented. The observer incorrectly treated the optional partial
map as the only geometry authority, so it lost valid history/editor/thread/tab
targets. Actual Window geometry was(71,3,105,31), PromptTextArea(75,39,100,1),
and both declared ThreadRow entries and the original SessionLabel were present
in the committed full map. Later screenshots remained readable.

The failed history helper raised ValueError; the peer helper raised StopIteration.
Installed `xdotool -` nevertheless continued through subsequent actions and
returned0. Key holds stayed in PromptTextArea, not HistoryWindow. Ctrl+End also
inserted literal `[J` before the draft. These are preserved counterexamples,
not evidence that production scrolling failed or succeeded.

Repair: read Textual's public `compositor.visible_widgets` once for native target
selection and resource visibility. That owner chooses its already committed
partial/full representation; the observer does not force layout, hold another
map, or implement a fallback reader. Every action is now a separately checked
native CLI argv through the existing ProcessOwner. Failed helpers abort the
capture; the unnecessary Ctrl+End gesture is deleted.

Actual isolated-X native negative check:
`physical-driver-native-exit-20260930.json`. `xdotool exec --sync /bin/false`
returned1; ProcessOwner raised CalledProcessError and retired both owned
processes with no leaks/errors. No application, keystrokes, provider calls or
native prompts were started by this check. Python compilation and diff whitespace
checks pass. The corrected physical236 journey remains integration-owner work;
this tools checkpoint does not claim product readiness.

Heisenberg236 owns the requested three-viewport buffer and production
cache/preparation integration. The severe mid-compaction tab-switch hang is a
separate reported lifecycle risk, explicitly handed to that integration owner
for a named cross-owner claim. This zero-input capture cannot prove it fixed.
