# Native style mutation and layout request have distinct lifetimes

Source: Styles._update_rules commits authored inputs, then DOMNode._style_rules_updated
retires descendant measurements and ancestor geometry through the original hooks.
Styles._refresh then calls Widget.refresh(layout=True), which treats the request
as another source mutation and runs _invalidate_layout/_measurement_updated again.
Raw style writes must remain synchronous source invalidation without unsolicited
refresh; imperative content refresh must still invalidate before an await.

Use the existing style-notification / Widget layout publication family to carry
already-published style requests. Keep source mutation owned by Styles and ordinary
Widget input mutation owned by its current public refresh contract. Delete repeated
retirement from style scheduling, not legitimate layout or actual content writes in
leaf notify hooks. All original native/Toad overrides retain their public contract; scheduling callers migrate coherently;
no new mirror, cache, flag, typed wrapper, scene map, timer or alternate renderer.
The existing public style callback keeps its signature and behavior; source review
rejected introducing a new keyword to existing subclass callbacks.

Native ownership: Widget/DOM style-to-layout scheduling, Styles notification callers,
original native widget overrides. Heisenberg owns Toad source/admission/preparation/
paint/retirement and its eight style-notification overrides; coordinate the exact
shared boundary directly. No edits to his worktree. Native52/53 source and installed
qualification stay frozen on main and are not a performance finish line.

Current main c1c1ebe5; existing NRA Package complete native249 and Toad288 parsed with
zero omissions. Source activation from original422 is not CPU dominance or a latency
measurement. Read all declarations, writes and hooks before implementation. Coherent
family implementation first; affected controls and one changed installed user path
last with the workflow owner. No old film, new worktree/environment/native copy or
parallel measurement project. Full structural UI responsiveness remains active.

## Working owner implementation

Existing Widget now owns `_request_layout(required: bool = True)`: it joins the
actual native `_layout_required` work flag without retiring source inputs or
triggering idle on its own. DOMNode supplies the non-rendered no-op hook. Public
Widget.refresh(layout=True) still calls synchronous _invalidate_layout FIRST, then
requests the original Layout publication and preserves its ordinary idle/paint
lifetime. Styles._refresh requests that same publication after existing authored
source invalidation, then retains original paint/idle/notify behavior. Child
inherited refresh requests and DOMNode.reset_styles use the same owner. The third
foreign flag write was reset_styles, not a _refresh_styles method.

No notify_style_update signature changes: all nine native/eight Toad leaf hooks
retain their independent content/style/worker preparation behavior. New content
mutations in those hooks may legitimately invalidate again; only treating the
same style-frame request as another input mutation is deleted. BodyMeasurement's
synchronous invalidation/participation change remains untouched, as do its genuine
refresh(layout=True) tree publication consumers. No copied frame flags or source
frontier, no cache/map/type, no source/receipt/follow semantic bypass.

The first published checkpoint was source-only. The completed native App batch
is recorded below; installed Toad qualification remains pending. No old film or
environment/package launch was made for this source pass.

## Complete caller closure and final native App batch

App's existing refresh forwards to the current Screen. App therefore overrides
the same _request_layout hook to forward already-invalidated style publication;
its public refresh(layout=True) still retires actual Screen content inputs.
The mounted-App control verifies source retirement once and actual Screen
publication, preventing a silent App-level lost-layout regression.

Screen's remaining flag writes belong to its native frame lifetime: _on_layout
joins child Layout messages, _on_timer_update consumes the admitted reflow, and
inactive presentation retirement requests reconstruction of released resources.
Screen prevents Widget's default idle handler and consumes its own pending work.
Those decisions remain with Screen. No unrelated flag/map/lifetime is unified.

The native family closes IMPL-13/BOUND-2: scheduling uses the existing layout
publication owner instead of repeating its source-retirement algorithm. Four
production files change 23 added/24 deleted lines; no source counters removed.
The existing programmatic-style App batch plus two concrete lifetime controls
passed 14 cases in 1.60s. They cover native grid/align children, cohort atomicity,
offset retained paint/hits, raw-style synchronous geometry invalidation without
unsolicited layout, separate frame publication, actual new-content height/paint,
and App-to-Screen layout delivery. This is source App qualification, not an
installed Toad recording or demonstrated CPU gain. The changed installed workflow
remains with Heisenberg's existing holder after its current F4 lease is returned.

The original packaged F0 ratchet exits 0 against main c1c1: no admitted
measure grows; Styles GodClassExcess decreases by one, all other deltas zero.
App/DOM/Widget source-to-frame hooks replace existing family work; no waiver,
threshold or scanner change. Hosted Debt must bind the final published head.
