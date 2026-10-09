# Retained widget transfer

`Widget.reparent(parent, before=None)` moves a mounted subtree within its current
application without composing it again or restarting its message pumps/timers.
It is intended for a genuinely shared presentation, such as application-wide
navigation reused by multiple screen modes.

The owning native boundaries remain authoritative:

- NodeList and `_attach` publish the new ancestry and invalidate native queries.
- The old screen releases derived scene ownership; both parents request layout.
- Styles are resolved in the destination context. Unchanged cached line content
  may survive; this is not a promise to skip required CSS/layout/paint changes.
- Focus, selections and sender-owned pending frame callbacks transfer to the new
  screen. Removing the old parent does not close the moved subtree.
- The application registry, widgets, child identities and running tasks survive.
  Mount/Unmount are not emitted for the transfer; ordinary close still emits
  Unmount once.

Invalid destinations, cross-application moves, cycles, duplicate sibling IDs,
screen moves and closing/unmounted nodes are rejected. A mouse-captured subtree
must release capture first. Explicit subscriptions to a particular screen remain
the caller's responsibility; the API does not rewrite arbitrary user closures or
subscriptions. Toad's shared Channels tree uses application-owned signals.

Five new regressions cover identity/tasks/styles, old-parent removal, cross-screen
focus/selection/scene cleanup, atomic rejection, insertion order, pending frame
callbacks and mouse capture. The original three tests failed before the method
existed. Focused scene/watch tests pass; the complete framework run passes
**3,512 tests**, 1 skipped, 4 xfailed in 200.77 s. Peak memory 250.8 MiB with a
4 GiB/no-swap cap and one pytest worker. Companion Toad tests exercise the same
Channels rows and cached paint across new, pending and existing tabs.
