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

Status: implementation and regression checks in progress. This is presentation
grouping, not a new execution-turn authority or inferred provider lifecycle.

## Further cleanup

Use subsequent user screenshots to refine spacing, role labels, grouping, and
other message presentation. Keep each correction and its validation recorded
here; broader formatting choices have not yet been specified.
