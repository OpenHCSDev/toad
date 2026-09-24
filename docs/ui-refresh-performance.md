# Conversation tab, sidebar and idle-refresh checkpoint

This checkpoint targets the thread/channel views and their sidebars.

## Avoided work

- Resuming a view after new CSS sources were registered applies changed rules to
  matching targets and their inheriting descendants. Removed rules, virtual
  components, source ordering and theme/root-class changes remain covered.
  Completed full style updates record their revision, so breakpoint classes do
  not force another complete refresh on the next visit.
- Shared sidebar collapse intent still reaches hidden views. Their visual
  geometry is updated inside the next activation transaction. An open/close
  round trip therefore avoids invalidating every hidden conversation.
- Opening a sidebar queues its native header focus before the first paint,
  rather than requesting a second focus/paint cycle afterward.
- Right-panel polling retains unchanged sort labels, context text, disclosure
  glyphs and unavailable-row text. Text and styled spans are compared; new
  activity, membership, order and tooltip data are still reconciled.
- ASCII unread-count changes within the same digit range repaint channel badges
  and tab labels without requesting full layout. Showing/hiding a count, changing
  digit width, changing a title, and adding/reordering tabs retain layout updates.
  Paint-only unread changes do not recenter the tab strip unnecessarily.

## Reproduced idle problem

A mounted right-panel fixture with 734 widgets reproduced one full-screen layout
for each unchanged snapshot revision. The sort control called `Static.update()`
on its identical auto-width label. Its unchanged context/disclosure text also
requested redundant paints.

At the normal 50 ms observation interval, a four-second fixture observed:

| Measurement | Before | After |
| --- | ---: | ---: |
| Completed polls | 80 | 80 |
| UI process CPU | 41.16% | 6.39% |
| Full layouts | 79 | 0 |
| Paints | 79 | 0 |

This is a controlled same-data polling workload, not a prediction for every live
session. It retains the polling cadence and data reads. Separate regressions
verify that changed activity is painted, sort-width changes still lay out, and
unread counts remain visible through digit-width and zero/nonzero transitions.

## Tab/sidebar terminal evidence

A disposable Xvfb/st fixture with two thread views, two channel views and a
60 Hz application timer compared actual conversation/sidebar pixels against
settled native references. New unrelated CSS was registered after acquiring the
references to exercise aged-tab returns.

| Operation | Before median / worst | After median / worst |
| --- | ---: | ---: |
| Tab return | 47.78 / 151.05 ms | 40.37 / 52.21 ms |
| Sidebar toggle, including focus | 138.01 / 194.24 ms | 96.05 / 110.23 ms |

The two thread references and expanded/collapsed sidebar references matched
pixel-for-pixel across the comparison. This bounded fixture does not establish
the separate <16 ms target or long-running live-session acceptance.

## Checks

With the intended Toad/Textual checkout on `PYTHONPATH` and compatible core
dependencies, the focused regression entry points are:

```sh
python tests/relationship_poll_reflow_pilot.py
python tests/unread_paint_only_pilot.py
python tests/sidebar_metadata_reflow_pilot.py
python tests/sidebar_projection_pilot.py
python tests/resume_style_revision_pilot.py
python tests/right_comms_integration_pilot.py
python tests/tab_history_controls_pilot.py
python tests/channel_views_pilot.py
```

The new polling and unread tests also pass with packaged Textual. Existing
navigation, sort, channel visibility, thread activation and footer checks are
retained. This checkpoint does not change the core dependency pin or resolve its
independent startup/feature-review gates.

## Remaining work

Live feedback confirms faster repeated tab changes and fewer hangs, but first
thread/history loads and the Channels sidebar can still take too long. Read-only
inspection observed a large queue for the core message-store lock, with a UI
snapshot reader waiting while holding the broader wire lock. Reader contention
and first-use foreground work still need separate diagnosis and correction.

Selection/highlighting and tab switching remain performance priorities. The next
checkpoint should prepare reusable data in persistent background workers and keep
input responsive during first-use preparation, showing a spinner before work
that is not ready. The current results do not satisfy a no-stall or <16 ms claim.
