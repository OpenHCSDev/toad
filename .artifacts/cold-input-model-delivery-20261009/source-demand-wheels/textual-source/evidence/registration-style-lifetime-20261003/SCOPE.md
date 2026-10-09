# Initial registration style lifetime

App._register currently completes descendant styling and notification before
applying their parent's initial rules. Styles._update_rules then publishes the
parent mutation through DOMNode._update_inherited_geometry, retiring resources
that those descendant notifications just acquired. Complete attachment and
default CSS collection also finish after some initial notifications.

Keep the algorithm on App._register. Attach the complete incoming native tree,
apply initial rules with ancestors first, then notify and start messages in the
existing descendant/group order. Preserve sibling insertion, original hooks,
positional selectors, virtual components and ordinary later invalidation. No new
cache, state flag, registry, owner type or alternate stylesheet path.

Heisenberg granted this native registration/style family. Frozen PR41 c4e5fd22
and its joined 393 recording remain unchanged. This draft is stacked on PR41
until that checkpoint lands. Existing NRA Package parsed all 249 native and 289
Toad production modules without omissions; actual dynamic receiver/MRO requires
semantic reading. No Toad registration override was found.

Source implementation precedes one batched affected native sanity check and the
next joined installed journey. Registration is an observed source path, not a
measured dominant CPU share. This does not close IRC End or scrolling smoothness.

## Working source checkpoint

App._register owns the entire synchronous admission. Its local traversal returns
the original descendant/group notification sequence after attachment and CSS
source collection complete. Initial stylesheet application consumes that sequence
in reverse, so ancestors commit before descendants. Notification and message
startup then consume the original sequence. The old recursive _register call,
which also styled/notified/started each partial subtree, is deleted. The original
_register_child remains the only attachment/post-register hook; no behavior is
copied into a new owner.

All production entrypoints share this change: Widget.mount and App's screen/mode
registration. Virtual scrollbars retain their separate existing _start_widget
lifetime. Styles._update_rules and DOMNode._update_inherited_geometry retain all
ordinary mutation/measurement invalidation, including inherited opaque visuals.
Stylesheet.apply retains component processing and its original shared rule cache.
No invalidation is skipped, and no retained rendering or semantic state is added.

Production delta: one file, 28 added / 14 deleted lines. Pattern IMPL-12: remove
repeated partial lifecycle publication by making the existing App admission own
the whole incoming tree. AST sites identify static source only; custom dynamic
receiver overrides cannot be inferred from names alone.

## Batched native sanity

After the coherent source checkpoint, 17 native checks passed in 12.79 seconds:
test_mount.py, test_widget_mounting.py and test_screen_modes.py. These check
startup/eager composition, insertion and mount ownership, screen lifecycle, and
the new incoming-tree case. That case uses an actual App with native widgets:
each initial notification sees inherited parent color and the later sibling's
unscoped DEFAULT_CSS declaration, while notification order remains unchanged.
It uses no widget, stylesheet, protocol or provider replacement.

Source checks reused system Python/installed dependencies with the checkout's
src on the import path; this is source verification, not an installed wheel gate.
No environment/build/provider/capture was created. Resource preflight reported
home 6.2 GiB, RAM available 13.2 GiB and swap used 14.9 GiB; the bounded in-process
batch reused existing dependencies and completed without a parallel fixture.

NRA before/after source evidence covers all 249 native production modules with
zero omissions: selected registration/damage declarations and calls 40 -> 39.
The removed call is recursive full registration/lifecycle publication. All three
external registration entrypoints remain. Retained before/after source is in
owner-before.json / owner-after.json; result is in native-sanity.log.

This source checkpoint is not installed Ready. The next joined changed installed
journey remains Heisenberg's; frozen 393/41 evidence is not reused as changed42
acceptance. Original IRC End and scrolling-performance gaps remain open.
