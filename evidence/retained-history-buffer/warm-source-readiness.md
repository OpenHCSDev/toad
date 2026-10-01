# Original native workspace readiness for the physical source journey

The source fixture has two actual workspace views and the protected original
41 MB journal. It has no ACP actor. Its `WarmSourceJourney` now derives the
intended B mode from the same `PeerTabTarget.locate` and captured original A
snapshot that govern the physical tab click. The marker verifies the captured
UI PID and the original snapshot's UI identity before selecting that mode.

The existing capture observer waits for that selected mode. It retains every
existing shown-source, visible history, ready body, mutation/lock, frame-ready
and terminal `FrameFlush` acknowledgement requirement. The external CLI admits
one thread or native mode selector, never both. Real-agent warm journeys retain
their original thread identity selector. No product identity, state or cache is
created or changed.

The parked-history concern was checked against both current source trees:
`Conversation.prepare_retained_session` calls `resume_retained_history` when
there is no agent, and each original history state owns `resume_if_parked`.
`NativeSessionSurface.activate` already invokes that original lifecycle. No
extra fixture callback, fake agent or direct source-state write was added.

Preflight: all three changed tools parse with the selected runtime Python;
`git diff --check` passes; the existing recorder generates the canonical
`warm_source` action script without requiring `--peer-thread`. This is a tool
contract checkpoint, not a physical capture pass. The single physical capture
and CPU/video correlation remain pending. The original native demand reversal
RED/GREEN and all earlier failures stay preserved and are not rerun.

Deletion at this checkpoint: 15 tool lines replaced, no production deletion.
The production demand fix remains 3 added / 3 deleted lines in
`DocumentViewport._reconcile`; its original demand is the sole admission owner.
