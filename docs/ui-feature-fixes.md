# Screenshot-driven UI fixes

This draft tracks UI issues reported with screenshots and the fixes verified
against them. The starting point is Toad main at `e3f86d8`, including the merged
prompt-failure reasons and ACP log links.

## Batch 1: header and sidebar geometry

Reported with six screenshots, followed by mirrored-slider and draggable-edge
requests. All items below are implemented and covered by mounted checks.

| Issue | Cause and correction |
| --- | --- |
| Menu/history controls appeared on the right, leaving tabs offset. | Removed right docking and sidebar-dependent header padding. Controls start at the screen's left edge; tabs fill the remaining row on native and channel screens. |
| Shrinking a sidebar hid its vertical scrollbar. | Long rows widened an inner scroll container past the viewport. One fixed sidebar viewport now owns both native scrollbars; content can grow inside it. |
| A duplicate horizontal slider appeared below the controls. | Removed the separate scroll slider; retain the native horizontal scrollbar, shown only when needed. |
| Move/Float controls lacked visible hover feedback; arrows were too small. | Added explicit ANSI/RGB hover/focus styles and wider multi-character arrows. Arrows are ordered left then right; batch 2 below refines their spatial behavior. Narrow bars put Float/Push on the next control row. |
| Collapsing one bar left a gap beside its floating peer; Float could reorder bars. | Resolve both bars from actual widths, including collapsed handles. All bars pack together independently of Float/Push; only the conversation gutter changes. A pushed inner bar reserves space through its inside edge. |
| Width slider direction was wrong on the right. | Mirror track, label, pointer mapping and arrow keys. Moving toward the screen center increases width on either side. Freeze the pointer mapping while dragging so resizing the track cannot undo the value on release. |
| Inner edge could not resize the bar. | Added a captured-pointer resize handle on the conversation-facing edge, green normally and white on hover/focus. It shares the 15–50% width setting with the slider and hides when collapsed. |

### Reproduction and validation

The initial 120×40 mounted reproduction failed for header placement, duplicate
slider, clipped vertical scrollbars at 50%, 30%, and 15%, and the collapsed
peer/floating gap. It now passes with ordinary and virtual rosters. Additional
checks cover same-side packing on both edges, mixed Float/Push, collapse/reopen,
actual pointer hit-testing, left/right drag capture, slider endpoints and keys,
ANSI/RGB hover, narrow controls, and native horizontal scrollbar interaction.

Run from this worktree using the pinned stack environment:

```sh
PYTHONPATH=src:tests /home/ts/.agent-comms/stack/.venv/bin/python tests/ui_sidebar_geometry_pilot.py
TOAD_BENCH_VIRTUAL_CHANNELS=1 PYTHONPATH=src:tests /home/ts/.agent-comms/stack/.venv/bin/python tests/ui_sidebar_geometry_pilot.py
PYTHONPATH=src:tests /home/ts/.agent-comms/stack/.venv/bin/python tests/sidebar_drag_resize_pilot.py
```

Related passing pilots: `sidebar_layout_policy`, `sidebar_layout_controls`,
`sidebar_nonvirtual_scroll`, `layout_alignment` (120 and 76 columns),
`sidebar_navigation`, `owner_navigation`, `main_menu_transfer`,
`right_comms_integration`, `thread_layout`, `virtual_sidebar`,
`virtual_sidebar_damage`, and the broad `comms_pilot.py`.
Names above refer to `tests/<name>_pilot.py`, except the explicitly named broad
pilot. Virtual keyboard navigation and scroll restoration use the same outer
viewport; retained-row versus full-redraw parity remains covered.

These checks use disposable wires and mounted test applications, not a live
user-session deployment or a terminal-pixel latency claim.

## Batch 2: spatial arrows and visible sorting

Follow-up reports from the PR preview, implemented and mounted-tested:

- **Wall and neighbor semantics:** the original move/swap button roles were
  fixed even when their arrow glyphs pointed at a neighbor. The placement
  model now resolves each left/right direction: swap with a same-side neighbor,
  otherwise move across the conversation if heading inward, or refuse the
  outside wall. Wall-blocked arrows are hidden. An outer bar has one arrow;
  an inner bar has two. Click handling resolves current placement again, and
  Float/collapse do not change the spatial rule.
- **Sorting:** wide content also widened its header, putting sort controls off
  screen. Panel and ordinary tree-group headers now stay within the sidebar's
  visible horizontal viewport while rows retain their full scrollable width.
  Sort controls stay right-aligned, with bounded/ellipsized captions on narrow
  bars. Headers still scroll vertically with their sections.

`sidebar_direction_pilot.py` first failed on the extra wall-facing arrow.
It now exercises real clicks through both same-side arrangements, inward and
outward swaps, cross-center moves, Float and collapsed neighbors.
`sidebar_sort_viewport_pilot.py` first found a sort control at x=131 outside a
viewport ending at x=46. It now verifies clickable, right-aligned sorting at
40%, 25%, and 15%, at both ends of horizontal scrolling, on both sidebars and
with ordinary/virtual channel rosters.

Passing adjacent checks include placement policy, sidebar controls, drag resize,
sidebar navigation, and the broad Comms pilot. Targeted Ruff checks, layout
policy mypy on Python 3.14, and whitespace checks also pass.

Preserve drafts, navigation ownership, read-marker semantics, copy/history,
scroll intent, and the merged renderer behavior while correcting each issue.
