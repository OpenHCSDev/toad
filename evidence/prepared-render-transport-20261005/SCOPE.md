# Carry prepared renderer values through their original transport

Base: `e32253a5601400234b7ef0b5a191185c7427647a` (merged 456 and 457).

## Source relationship

`RenderTask.preparation_storage` already declares result storage. Local workers
return raw graphs; persistent workers additionally encode/decode `ResultCapture`.
`RendererWork.execute` then serializes the returned graph for retention. The
existing `PreparedValue` can cross both boundaries without rebuilding that graph.

The task owns execution, result validation and representation selection. Renderer
backends own admission and transfer of that representation. `PreparationRuntime`
continues to own identity, cache cost/eviction, scope retirement, worker delivery
and shutdown. Each consumer still receives an independent mutable value.

Migrate the complete local and persistent backend family, its protocol codec and
the existing preparation consumer. Delete the raw result capture and subsequent
retention reserialization. Preserve direct renderer submit, warm-up, ACP result
validation and the original admission/cancellation/acknowledgement/lease fences.
Direct renderer submit materializes its captured value off the UI loop. The
existing Renderer now tracks these delivery tasks and joins them during backend
close; cancellation still reaches capture, while an already-running decoder is
joined before its owned submission retires. Preparation consumers retain their
original runtime delivery worker and scope fences. No widget, viewport, frame or
native SDK changes are made.

This follows BOUND-2 and TIME-9: use the representation owner already present and
remove the competing raw graph boundary. Source traversal evidence does not
establish measured CPU dominance, faster first paint or smoother frames.

## Coordination and acceptance

Einstein owns the renderer/preparation seam. Heis confirmed no current writer in
the seven renderer/preparation files and retains the viewport/body/frame/source
integration. Kepler retains native geometry/compositor ownership.

AST declarations and consumers are read before implementation. Proportionate
source controls follow coherent implementation. The affected installed Markdown,
Rich preview, local/persistent renderer and independent delivery path remains a
future named purpose; no package, runtime, provider or capture loan exists here.
The accepted 456/457 checks and original negatives remain frozen.

## Work removed

For reusable results, the local transport no longer reconstructs the token/strip
graph merely for preparation to pickle it again. The persistent transport also
keeps that prepared representation through its service/reply boundary. The
process pool and private protocol still serialize their transport envelopes;
this change removes graph traversal, not all byte transfer or copying. Each
foreground consumer still materializes its own graph. Warm-up validates/captures
without materializing an unused consumer result.

The complete Renderer subclasses and existing observing/gating controls migrate
to capture. CapturedResult is removed; ResultCapture accepts PreparedValue through
its existing nominal boundary. Headless RenderExecution.complete remains the
separate original SDK validation path without a renderer or retention transport.

## Published source checkpoint

- Fourteen unique unittest cases and two existing policy controls passed at their
  source scope. The changed delivery-thread observation case additionally proves
  that task validation runs off the caller thread and cancelled decoding is
  joined by close. A real pure renderer worker, declared reply codec, independent
  Markdown results and persistent error/cancel/lease transitions were exercised.
- Two initial optional-dependency imports failed before cases. Two unchanged
  fingerprint checks failed on missing source dependency identity. All original
  outcomes/logs remain in `source-controls/`; no oracle was weakened and passed
  cases were not repeated to repair those dependency preconditions.
- The one normal Hatchling 1.28 filewheel has all 319 Git/local/ZIP assets equal.
  `FILEWHEEL.json` names its original path/hash. This is source packaging evidence.
- Final source coverage is 288 production modules and 397 test modules, zero
  parse omissions; all 17 changed Python modules compile. Local debt has no
  positive counters. No installed, physical, frame cadence or speed result exists.

`SOURCE-CHECKPOINT.json` retains exact results and limits. The existing installed
renderer control is prepared to cover both transports plus Markdown/Rich
independent delivery; it has not run. `FUTURE-INSTALLED-SCOPE.json` identifies its
literal control/hash and the required optional persistent-renderer dependency.
Heis retains the first-paint/moving-frame integration; a fresh eligible holder
purpose must bind the installed cohort before that work executes.
