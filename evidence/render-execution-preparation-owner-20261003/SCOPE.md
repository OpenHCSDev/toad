# Shared renderer execution and preparation ownership

Current source: merged PR362 / main 1a59f5d44. Reuses the existing checkout.

Source gap: RenderExecution declares the result contract, but local process and
headless ACP execution skip it; persistent CompleteReply applies it independently.
RenderExecution owns await-and-accept behavior, borrowed by execution backends and
headless ACP execution. Existing lifetime/cache adapters continue delegating to
those backends, without accepting an already accepted result a second time.
Persistent acknowledgement/cancellation remains with the original reply family.

RenderTask/ReusableRenderTask already own whether captured inputs support reuse.
RenderPreparation currently re-decides that through nullable reusable_inputs in
identity, retention, and storage. Move those behaviors to the existing task family
and have RenderPreparation borrow them; retain the single bounded PreparationRuntime.
No new task, runtime, cache, session, registry, transport codec or frontend family.
ReusableRenderTask selects existing SerializedWork; RenderTask selects existing
PreparationWork. Their existing storage classes own retention and copying. The
task family owns fresh versus content-addressed identity; RenderPreparation asks
those hooks without selecting cases. TaskCapture remains the sole declared-task
membership check, reused for pre-admission and the external codec boundary.

Heisenberg granted renderer/preparation methods. His PR364/Text33 registration,
style, viewport and leaf result contracts stay with him. Existing U1, U2 surface,
U4 permission/terminal and U5 model checkpoints remain implemented; this closes
the remaining shared execution/reuse slice, not the whole future frontend scope.

Read source and AST first; migrate the coherent owner and all consumers, then
batch final affected sanity and installed application/local/persistent/ACP checks.
No provider calls, new environment, public changes or repeated PR362 acceptance.
Patterns: IMPL-12 (copied orchestration), MEMB-2 (repeated task membership),
TIME-9 (do not preserve displaced internal shapes behind aliases).
