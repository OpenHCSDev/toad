# First-update validation and worker startup

Based on current main 6d741e75d (merged583, production source identical to
installed c22db896f). Earlier80d9 remains published/integrated. Core608d5033 and
84c312dd are retained checkpoints in the same cold-open workflow. Original clocks
remain in their original evidence files; buffered-line gaps are not capture costs.

## Required ingress and delivery

AgentProcess reads a line, logs it, and awaits IncomingWireMessage.receive.
Ordered session/update dispatch enters SessionNotificationOwner.receive under
its existing lock and captured ClientSessionRequest. ApplicationValidationOwner
submits ValidateSessionUpdateTask through PreparedRenderer/PreparationRuntime.
The worker validates the official SDK SessionNotification, then NotificationItems
checks the SDK plan policy that otherwise silently drops invalid entries.
decode_updates independently validates backend extension facts through FieldCodec.
These are different required answers, not duplicate decoders.

DecodeCommsMetadataTask handles request/response metadata that is not a complete
SessionNotification. Load metadata carries configuration/goal/queue/cursor facts;
the original supplied history page arrives in TranscriptSnapshotUpdate. Removing
response decoding or substituting that page would lose independently changing
metadata. Both original task types and their codecs remain unchanged.

RenderTask.capture_result owns validation and the declared prepared representation.
The process pool transports PreparedValue; Renderer/PreparationRuntime materialize
it in existing thread workers, then validate delivery. SessionNotificationOwner
rechecks captured authority before typed MRO dispatch. Snapshot publication retains
original session/surface/source fences, preparation and mounted-frontier admission.
Notification ordering and source/session currentness are unchanged.

## Repair through original startup owners

App.on_load now starts its selected existing renderer. RenderProcessPool.start
acquires its configured workers once, using the original executor field. Importing
or constructing a pool still starts nothing. RendererSpawn owns shared real pool
launch; both the local pool and independent RenderService use it. The persistent
service retains its original build checks, request identity and lease lifetime.
Remote clients still connect on demand.

The shared initializer clears inherited agent identities, then imports the actual
sdk_boundary declarations. Required SDK/schema imports now finish during worker
bootstrap instead of unpickling the first ordered task. No fake notification,
dummy rendering task, second registry, adapter or cache is created.

Deleted the first-paint warm-up flag, App display trigger, Renderer Markdown/Patch
dummy submissions, PreparedRenderer forwarding method and their obsolete pilot.
Formatting/preparation now receives actual viewport work. Existing spawn context,
capacity, cancellation accounting, worker replacement and joined shutdown remain.
CPython ProcessPoolExecutor has no public prestart operation: RendererSpawn uses
its original launch/manager hooks before submissions and closes the executor if
launch raises. Qualification here is Python3.14.2, the required installed runtime.

AST via NRA covered Core, current Toad and native production roots:862 modules,
zero omissions. Determining sites are in before-consumers.txt. Changed modules
were parsed/compiled and their installed bytes verified against wheel/source.
Dynamic external/pickle imports are not exhaustively resolved by this AST pass.

## Installed original saved attachment

Both comparison runs use Core84c312dd, native0fbb915d, ACP SDK0.12.1, original
saved agent-comms-ux owner477574 and canonical frontier147260275. Baseline is
installed c22db896f/current-main source; candidate contains this owner repair.
Both use copied original settings and actual captured seven visible categories.
No source/session fork, owner restart, user/provider input or global installation.

The existing observer was corrected to import App/SDK instrumentation only inside
its guarded main. Previously, spawn replayed those top-level observer imports in
children, unlike the guarded installed CLI. Original old clocks are retained,
but their1.342/1.498s handler durations are not the corrected baseline below.

| Seconds | Current-main baseline | Completed candidate |
| --- | ---: | ---: |
| First ApplicationValidationOwner call | 0.543 | 0.021 |
| Initialize | 2.587 | 1.210 |
| Session-load | 1.152 | 0.546 |
| App open to visible history | 5.427 | 4.133 |

Starting processes alone left first validation at0.446s. Required SDK declaration
imports were still deferred to the first task; moving them into the initializer
completed the repair. That intermediate measurement remains in the existing
artifact directory, not a separate published branch or claimed result.

The demonstrated first-update wait reduction is about522ms. Total opening also
changed, but initialize varied materially under host load: this single comparison
does not prove a repeatable1.29s end-to-end gain or resolve the whole reported5s.
The completed run still took4.13s; initial page publication/preparation took0.872s.
Remaining source, ACP initialization and visible preparation work is not removed.

Both original Apps finished without error or provider input, with four visible
bodies and loading0. Five existing process-pool checks passed after the completed
SDK bootstrap, covering spawn identity/import safety, errors, bounded parallel
admission, cancellation and joined shutdown; CPU heartbeat maximum gap11ms.
No mock startup score or provider replay. Optional persistent transport is absent
from this runtime: its source family was migrated, but no persistent installed
acceptance is claimed. Original worker477574 was preserved, so Core owner-side
TranscriptReplay encoding still awaits reviewed worker installation.

Private copied settings/state were removed after App teardown. Compact original
clocks are retained here. Candidate wheel/runtime/control remain under
.artifacts/cold-validation-bootstrap-20261008 for Parent integration. Public
launchers/packages are unchanged; independently qualified frontend work can ship.
