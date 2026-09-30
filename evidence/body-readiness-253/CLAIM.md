# Body readiness contribution to253

Einstein contributes to Heisenberg's existing253 integration owner. Source base
aec56e08 on merged249. This branch owns only ViewportBody/MeasuredViewportBody
readiness, DocumentViewport.visible_bodies_ready, and TranscriptFragmentView
readiness/retirement/restoration. Budget, reconciliation, measurement cost,
Conversation, publication, checkpoints and user submission stay with their
existing owners. Kepler251 owns TranscriptBlockConsumer.user in the same file.

Required relation: a frame may publish when its original visible body resources
are ready. A fragment's initial native Mount joins nested composition, but later
disclosure/tool expansion can mount bodies after that event. Mount completion
and body readiness remain distinct. The current property walks every descendant
of each visible fragment on every frame, including nonvisible resources.

Use the original compositor's visible widgets and the original native ancestry
for window membership; ask each visible ViewportBody's declaration once. Retain
the descendant readiness requirement when actually pruning a fragment, not in
the per-frame property. No new semantic bit, body registry or readiness cache.
Patterns: BOUND-2 original resource consumption; IDEN-7 check only the question;
IMPL-5 one readiness implementation on the original body declarations.

Acceptance is one continuous real native-widget journey through initial held
mount, later body expansion, retirement/restoration and paint. Source preparation
does not claim CPU savings or installed performance. One affected original
scroll/profile comparison follows a working delta through existing253 ownership,
not an independent fixture fleet. Preserve all native/UNKNOWN/default sources.
