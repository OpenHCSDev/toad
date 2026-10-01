# Existing-owner viewport feedback repair

Order: semantic source ownership and caller analysis, coherent implementation and deletion, then batched sanity and actual installed busy-user validation. Previous discriminator-first instructions are superseded; historical observations remain evidence.

## Required relations and existing owners

DocumentViewport owns the bounded body admission worker. DirectionalPreparation owns measured input travel, direction and expiry. WindowRestoration owns geometry compensation. HistoryWindow owns native resize/clamping and tail-follow application. WindowMembership owns retained window registration. MeasuredViewportBody and its existing BodyMeasurement own extent and resource cost. No new classes, second registry, layout-proof cache, ignore flag or scheduler are introduced.

The screen-wide layout subscription fed DocumentViewport.request after its own restore/prune layouts. Remove that consumer. Native scroll now observes travel; source registration, source resume, actual native size/extent change, destination and the existing settle timer request the same worker. The frame gate still requests missing visible bodies. Global sidebar/chrome layouts do not independently create body demand.

Compensation is a translation of the preparation owner's tracked position, preserving unconsumed travel, velocity and expiry. Nested restoration accounts once at its outer boundary. Workspace wraps only actual source anchors; HistoryWindow wraps native size clamping and automatic tail-follow at their producers.

Height measurement no longer calls retained_widget_count. Admission updates the existing measurement cost against the original propagated NodeList revision. Between asynchronous mutations the reconciliation loop reuses captured protection; it refreshes protection after awaits. Rebinding delegates to the existing WindowMembership instead of updating foreign sets and leaving that membership bound to its old presentation.

Patterns: IDEN-1 (layout versus input travel), IDEN-5 (foreign membership copies), IMPL-13 (compensation producers), TIME-9 (reuse original native and presentation mechanisms). A new body or reader case inherits the existing contracts; it does not require another outside dispatch table. Runtime lifecycle is Arendt-owned, compaction Schrodinger-owned; neither implementation is changed.

## Actual declaration and caller search

```text
src/toad/widgets/conversation.py:334:    def rebind_screen(self, previous, destination) -> None:
src/toad/widgets/history_anchor.py:22:class WindowRestoration(ABC):
src/toad/widgets/history_anchor.py:45:                window.document_viewport.lookahead.relocated(window.scroll_y - previous)
src/toad/widgets/history_anchor.py:200:    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
src/toad/widgets/viewport_body.py:65:class BodyMeasurement:
src/toad/widgets/viewport_body.py:74:class MeasuredViewportBody(ViewportBody):
src/toad/widgets/viewport_body.py:218:class WindowMembership:
src/toad/widgets/viewport_body.py:236:class DocumentViewport:
src/toad/widgets/presentation_window.py:173:class DirectionalPreparation:
```

The complete source search has one declaration per listed owner. DirectionalPreparation.relocated has one production caller, WindowRestoration.geometry. Its two diagnostic callbacks migrate with the changed delta argument; no compatibility alias or fallback is retained.

## Preserved installed evidence and limits

Matched previous-source native491 busy gate: /home/ts/.cache/agent-scratch/perf275-native491-busy-input-warm-20261001-02. Native input-focused PageUp/PageDown moved chat and preserved draft/caret/focus (seven checks); middle-history and End screenshots readable. The combined driver exhausted its bounded interaction allowance during B opening; the overall receipt remains completed=false. It is not full warm or smooth-scroll acceptance. Raw profile, video and all original owners are preserved. This new semantic source batch awaits final installed validation.
