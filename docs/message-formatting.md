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

## Additional reported issues

- Incoming agent messages sometimes appear as User, with inconsistent inbound
  and outbound formatting. Investigating live metadata versus saved transcript
  routing; sender attribution must come from verified routing, not a regex over
  the visible `[agent-comms from ...]` text.
- Coordination context is hard to scan as a JSON dump. A readable lazy summary
  with original-source access is the next formatting slice.

## Further cleanup

Use subsequent user screenshots to refine spacing, role labels, grouping, and
other message presentation. Keep each correction and its validation recorded
here; broader formatting choices have not yet been specified.
