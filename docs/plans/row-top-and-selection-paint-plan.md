# Plan: row-top reader position and selection paint (protected paths)

Tristan approval requested before editing either protected path.

## Defect 1 — activating a row must leave its top visible

Symptom: clicking an expanded message/tool row does not bring its top into the
viewport; after expanding a long row the header cannot be reached to collapse
without hand-scrolling.

Cause (no scroll call exists today in the activation path):
- Click path `src/toad/widgets/transcript_history.py:139-143` (ToggleDetails link)
  and toggle owner `:553-555`; keyboard `:564-568`. All change fragment rows only.
- The reader-position owner is `HistoryWindow.reader_position`
  (`src/toad/widgets/history_anchor.py:283`); `FragmentPosition.destination`
  (`:186-190`) re-places the pre-existing reader and never re-anchors to the
  activated fragment.

Change (one owner, no scroll call in handlers):
- Row activation (click or key) records the reader position at the activated
  fragment's top — a `FragmentPosition` naming that fragment with row 0 / zero
  offset — through the existing reader owner. On expand and on collapse the
  layout then keeps the row's top visible; any other reader place is unchanged
  because activation is the reader's own choice.
- Expandable row family (saved fragments and live tool rows) shares the same
  activation entry, so live rows keep their current behavior and saved rows
  gain it.

Verification: real app on the isolated display with a row taller than the
viewport — expand from the input box, scroll into the body, activate collapse
by key and by click; row top visible both ways; reader not moved elsewhere.

## Defect 2 — text selection paints no highlight in the message area

Symptom: selection notification fires (copy works) but no highlight is painted.

Cause:
- Saved message rows are drawn by `TranscriptPageView.render_line`
  (`src/toad/widgets/transcript_history.py:261-275`), which returns
  `on_background(strip)` applying only `rich_style`
  (`src/toad/widgets/transcript_lines.py:207-215`). No selection styling.
- The fork's default `Widget.selection_updated` (`textual/widget.py:4104`)
  refreshes the widget, so paint happens — it just ignores selection.
- Existing canonical appliers for comparison: `worker_static.py:303-308` and
  `terminal.py:341-349` use `text_selection` + `Visual.selection_style` +
  `Selection.get_span` + `Strip.stylize`.

Change (paint-time canonical projection, no cached selection state):
- `TranscriptPageView.render_line` reads `self.text_selection` last and, when
  present, stylizes the drawn strip with `Visual.selection_style(self)` over
  `selection.get_span(y)` for that widget row, matching the established
  appliers. Selection cleared → plain row again.
- `get_selection` text extraction is unchanged.

Verification: real app — drag-select inside a saved message; highlight appears
and follows; copy unchanged; clearing selection repaints plain.

## Bounds

- Touches `widgets/history_anchor.py`, `widgets/transcript_history.py` and the
  shared activation entry only; no Textual fork change; no new state stores.
- No performance-series change expected; will re-run `capture_live.py` line for
  the scroll series if layout timing shifts.
- Tests last, real widgets/app; hook policy respected.