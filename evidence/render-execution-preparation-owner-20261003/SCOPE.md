# Shared renderer execution and preparation ownership

Current source: merged PR362 / main 1a59f5d44. Reuses the existing checkout.

Source gap: RenderExecution declares the result contract, but local process and
headless ACP execution skip it; persistent CompleteReply applies it independently.
Renderer owns submission; execution backends should provide its execution hook,
while lifetime/cache adapters continue delegating to that owner. RenderExecution
will own await-and-accept behavior, shared by renderer and headless ACP execution.
Persistent acknowledgement/cancellation remains with the original reply family.

RenderTask/ReusableRenderTask already own whether captured inputs support reuse.
RenderPreparation currently re-decides that through nullable reusable_inputs in
identity, retention, and storage. Move those behaviors to the existing task family
and have RenderPreparation borrow them; retain the single bounded PreparationRuntime.
No new task, runtime, cache, session, registry, transport codec or frontend family.

Heisenberg granted renderer/preparation methods. His PR364/Text33 registration,
style, viewport and leaf result contracts stay with him. Existing U1, U2 surface,
U4 permission/terminal and U5 model checkpoints remain implemented; this closes
the remaining shared execution/reuse slice, not the whole future frontend scope.

Read source and AST first; migrate the coherent owner and all consumers, then
batch final affected sanity and installed application/local/persistent/ACP checks.
No provider calls, new environment, public changes or repeated PR362 acceptance.
Patterns: IMPL-12 (copied orchestration), MEMB-2 (repeated task membership),
TIME-9 (do not preserve displaced internal shapes behind aliases).
