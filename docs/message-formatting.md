# Message formatting cleanup

This draft begins from merged main `eff5941` and tracks screenshot-driven
conversation-formatting improvements.

## First issue: missing Agent boundary before activity

The reported scene has a User separator and message followed immediately by
thinking summaries and tool calls. An Agent separator appears only when text
is emitted, leaving the first agent activity visually attached to the user.

Initial scope:

- Add an Agent activity separator before thinking-first or tool-first output.
- Handle a new user/follow-up message in an already-running session.
- Avoid another activity separator on every thought chunk or tool update.
- Keep existing text-message and routed-message headers, copying, disclosure,
  category filters, and scroll/follow behavior.
- Apply the same presentation rule to saved transcript fragments without
  repeating the separator on continuation fragments.

Status: implemented. A shared presentation boundary adds an Agent activity
divider before the first thinking/tool block after input or a new live turn.
The divider follows that block's filter category; saved continuation fragments
do not repeat it, and updating a thought retains its existing widget/header.
Existing text-message and routed-message dividers remain intact.

Validation: the new `agent_activity_divider_pilot.py` reproduced the missing
separator, then passed live thinking/tool-first, same-turn follow-up, duplicate
notification, filter and saved-fragment controls. Divider, fragment-divider,
native multipart-message, tool-diff, transcript-history, sparse-history,
in/out-filter, filter-supersession, worker transcript preparation and broad
Comms pilots pass. Targeted Ruff, presentation-policy mypy and whitespace
checks pass. Tests use an isolated environment with the branch's exact core
and Textual pins; no live provider or owner restart is involved.

This is presentation grouping, not a new execution-turn authority or inferred
provider lifecycle.

## Coordination context readability

Implemented lazy readable formatting for structured JSON and the native
`Peer state:` section. Peer records become a table; coordination instructions
and task context are separate sections. Other JSON objects/lists become
labelled fields and lists. Existing non-JSON Markdown is preserved. Invalid or
duplicate-key JSON stays in its original form rather than silently losing data.

Formatting runs off the UI loop only after expansion. An `Original payload`
disclosure retains the exact source, with literal rendering and unchanged copy
content. Reopening a disclosure reuses its body. The coordination-context pilot
passes readable-table, nested-field, raw-source/copy, lazy rendering, Markdown,
and literal-user-quote controls.

## Sidebar collapse ergonomics

Moved collapse handles to each bar's conversation-facing edge, beside the
one-cell resize handle. Left/right placement is mirrored; a collapsed bar's
handle still fills its three-cell strip. Content and controls reserve the inner
four-cell gutter, keeping scrollbars clear. Drag-resize, geometry (ordinary and
virtual), directional moves, pinned sorting, sidebar navigation and broad Comms
checks pass. The navigation pilot now uses the current ThreadRow open-selected
action rather than its removed legacy action name.

## Incoming agent attribution: companion core fix

The report of other agents' messages labelled User is reproduced **before the
UI renderer**, not repaired by the formatting changes above:

- Pinned core `74e157e`: `in_out_wire_replay_pilot.py` fails because a saved
  native framed input is returned as `user` with `routing=None`, while its
  outgoing send receipt retains the route. `TOAD_TEST_ANNOTATED=1` passes the
  same live/saved FROM/TO widget check with authoritative routing recorded.
- A bounded read of the actual `pr17-implementation` transcript returned two
  framed native `user` events without request/reply routing, alongside two
  `sent` events with outgoing routes. No prompt bodies are included here.
- The inspected core drain emits attributed `incoming` metadata for live views,
  but busy steering stores prompt text; `record_turn_routing` runs for original
  origins only after successful settlement. Saved injected-input provenance
  needs a core-owned exact native-input/session-entry binding.

The companion fix is [agent-comms PR #67](https://github.com/OpenHCSDev/agent-comms/pull/67),
pinned here at `73643680262ec810f2baf97a80b4f9593b96f025`. It persists authoritative
incoming routing by native input ID and exact sent-text digest, including busy
steering. Human/internal input bindings explicitly override stale turn routing.
No sender is inferred from `[agent-comms from ...]` text.

The new `native_input_attribution_pilot.py` checks mounted live/replay FROM/TO
parity, incoming body/copy text, human quoted-header controls, and IN/OUT
filtering. It covers fresh input bindings and historical repair from existing
native-ID disposition receipts; repair does not acknowledge delivery.

Historical repair is preview-only unless explicitly applied, and missing
receipts remain unattributed. No live history repair or owner restart has been
performed. This draft depends on the published core branch until #67 merges.

Integration includes Toad main `2b9a55d` and its goal snapshot/editor and input
delivery changes. The core pin includes their required owner contracts. Core
local validation passed 1,419 tests with 46 skips in 32.15 seconds using xdist,
with 88.81% coverage; no CI wait is required for this workflow.

Installed-pin validation: 22 independent pilot scripts passed with up to four
processes in 77.89 seconds, covering attribution, activity/context/dividers,
native message parts, transcript parsing/history, filters, sidebar layout,
goal editing/polling/history, input delivery, tool diffs, and broad Comms.
The drag-resize pilot separately exited zero in 7.78 seconds with isolated
stdio (the captured-output harness had retained a pipe after successful exit).
The three formatting/attribution pilots passed again after import cleanup.
Targeted Ruff and Python 3.14 mypy for the two pure presentation modules pass.

## Already-open thread links

Fixed the reported tab flicker: `open_thread_session` created and focused a
provisional loading tab before route discovery found an already-mounted
destination. It now first matches the requested root/thread against mounted
session identities and focuses that exact screen. No loading tab or metadata
read is needed for that match. Unknown aliases and noncanonical roots retain
the authoritative off-loop discovery path; genuinely new threads retain their
loading view, duplicate-click coalescing, and stale-result protection.

`existing_thread_link_pilot.py` reproduced the transient tab before the fix and
now passes actual pointer clicks, repeated/self navigation, same-name foreign
root isolation, unchanged tab order, and draft preservation. Pending-thread,
navigation preparation, sidebar opening/navigation, asynchronous thread open,
stopped-thread/read-boundary, native attribution, and broad Comms pilots pass.
Two existing pilots now drain background readers before temporary-wire cleanup;
the sidebar pilot also waits for animations before capturing exact scroll
baselines, retaining its exact frame/scroll assertions under parallel load.

## Further cleanup

Use subsequent user screenshots to refine spacing, role labels, grouping, and
other message presentation. Keep each correction and its validation recorded
here; broader formatting choices have not yet been specified.
