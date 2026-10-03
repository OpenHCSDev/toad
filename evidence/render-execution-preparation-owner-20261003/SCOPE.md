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

## Qualified checkpoint

Six production files: **44 added / 23 deleted**, no new classes or semantic state.
Normal main integration retained the tested production bytes. Exact ready source
and evidence are in `READY.json`; both AST outputs use the existing NRA parser
across all 286 production modules, with zero parse omissions and explicit limits
on dynamic receiver resolution.

- Installed01: actual local process/persistent ZMQ/headless ACP validation, typed
  SDK accepted/rejected results, independent non-reusable admission and reusable
  delivery: PASS, 5.253 seconds.
- Installed-app03: two real installed Toad applications reused the same renderer;
  Markdown, native patch, file preview and Read output completed. PASS.
- Four codec/reply/real-service family checks passed; source delivery retirement
  and shutdown checks passed. Earlier missing-dependency, resolver and old fixture
  failures remain committed with their exact classification.
- Existing private485 was reused after Sch/Bohr released it. All 317 source files
  matched the installed normal wheel. The five existing declared persistent extra
  packages bring that private check to 74 distributions, all dependency-compatible.
  Public defaults/native donors were unchanged. No new environment, provider
  input or native build; no latency, frame speed or physical-pixel claim.
- Owned fixture processes are absent and the actual renderer service was closed.
  Cleanup and the source proof are committed alongside the terminal results.

Remaining broader U2 work: native dependency imports in transcript_fragments and
patch_diff. This checkpoint does not claim the whole headless/frontend plan done.
