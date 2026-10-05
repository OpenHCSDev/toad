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
Rich, local/persistent renderer and independent delivery path passed under the
explicit joint #458/#460 purpose below. Einstein's operator claim is returned;
no provider, native artifact execution or physical capture loan was used.
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
  positive counters. At that checkpoint no installed, physical, frame cadence
  or speed result existed.

`SOURCE-CHECKPOINT.json` retains exact results and limits. The existing installed
renderer control is prepared to cover both transports plus Markdown/Rich
independent delivery; its original prepared scope was unrun.
`FUTURE-INSTALLED-SCOPE.json` identifies its
literal control/hash and the required optional persistent-renderer dependency.
Heis retains the first-paint/moving-frame integration; a fresh eligible holder
purpose must bind the installed cohort before that work executes.

## Exact installed proposal

`PROPOSED-INSTALLED-OPERANDS.json` fixes the original control command, environment,
short private IPC output and operator handoff. Bohr identified former public334
as a possible holder; its actual current447 floor, archive, aliases, borrowers
and restoration operands still require a fresh issued purpose. No prefix was
read, imported or changed during this preparation.

The recorded 69-package cohort needs five optional packages: zmqruntime 0.2.24,
python-introspect 0.1.14, portalocker 4.4.0, NumPy 2.5.3 and PyZMQ 27.2.0.
Their original metadata supplies the active requirements. Existing recorded
annotated-types, metaclass-registry and psutil versions satisfy the remaining
requirements; the actual eligible floor must verify them before launch.

The three small cached archives passed their RECORD checks. NumPy and PyZMQ
cache indexes had missing payloads; that preparation failure is retained.
Five original wheels were fetched once using their exact cached URLs and
SHA256 values, with no resolver, build, shared cache or installed-package write.
`OPTIONAL-CACHED-ARTIFACTS.json` and `OPTIONAL-WHEEL-RECORD-PROOF.json` bind every
wheel, metadata and verified RECORD. The owned originals occupy 17,832,699 bytes
under `/home/ts/.cache/agent-scratch/einstein-render458-pinned-extra-wheels-20261005`
and remain held for the named future purpose and restoration.

Heis has normally joined this source into #460. He owns its complete union,
one normal union wheel and the overall stage/restoration; the standalone #458
wheel is not claimed equal to #460. The proposed sequence stages the union once,
runs this one renderer control, returns Einstein's operator custody, then runs
Heis's changed cold-height control if the issued shared purpose includes it.
There is no accepted #456/#457 replay or measured first-paint/frame gain here.

## Scoped installed acceptance

The original frozen `0fb55331` control ran once through installed
`BoundedRun.session` under issued joint purpose `262ae8f4`, with the exact argv,
environment and cwd. Heis staged the normal #458/#460 union wheel `7546bd15`
and bound the complete 953-asset/full-74 proof before the operator handoff.

Terminal exit 0 in **10.719 seconds**; the control completed in 7.769 seconds.
Actual installed local spawn and private persistent ZMQ passed official SDK
model validation, wrong-result refusal, reuse/retention rules, and independent
Unicode Markdown and Rich token/strip delivery. These are renderer and SDK
model contracts, not an ACP agent or native SDK process.

The original control joined runtime/cache/pool closures, asserted pending work
empty, shut down its persistent service and restored its multiprocessing child
preimage. Original controller and child are absent, session groups and owned
sockets empty. Individual worker/service births were not captured by this
frozen control; no identities are invented. Candidate proof and DTO remain
byte equal. `INSTALLED-SCOPED-CHECKPOINT.json` and `installed01/` preserve the
original result and operator-return evidence. All earlier negatives remain.

Einstein explicitly returned READ/operator custody to Heis and Bohr. Heis owns
the separate cold-height App check and whole actual holder-floor restoration.
No native artifact execution, provider/input, mounted GUI, physical pixels,
first-paint/frame performance or speed improvement is claimed here. #461's
pending initial-prompt App work remains a separate future purpose.
