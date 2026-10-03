## U1 ready checkpoint

Application events now use one UI-independent `CoreEvent` family, the existing `FieldCodec`, one original-owner `CoreEventStream`, and one generic Textual carrier. All nine supplied headless UI plans were read; this PR closes U1. U2 service extraction stays with this owner and is not claimed complete.

### What changed

- Deleted `acp/messages.py` and its per-event Textual definitions and production imports. ACP output, plan, tool, permissions, configuration, failures, readiness, queue and cursor consumers use the same data family. Emission-time identity remains with its original owner; resources travel through the subscription, never the wire payload.
- SessionTracker, TabOrder, CoordinationAccess and ToadSettings publish through their original event streams. Deleted the six App Signals, the TabOrder Signal and their application consumers. The native Screen visibility Signal remains a borrowed rendering resource.
- Workspace requests compose the existing Command contract; deleted SessionAdmissions' duplicate request dispatch roster. Input/configuration, preferences, navigation, historical links, goals, command completion, filesystem invalidation, observation and transcript coverage use the same carrier.
- Deleted MainScreen/Conversation title copies, the internal nullable SessionUpdate mutation record and the duplicate incoming-sequence extraction. Original SessionDetails/SessionTracker and TranscriptCoverage carry that behavior.
- The existing AttachedSurfaceBinding owns subscriber lifetime. Native callbacks, terminal projections and permission futures keep their original custody. Retirement revokes queued delivery; no new state registry, compatibility alias, alternate codec or per-event frontend mirror.
- Remaining Textual messages own editor, pointer, menu, pager, question callback or terminal resources. U2 owns broader service extraction.

Against reviewed main `0a522a8a`: **1,222 production lines deleted, 1,573 added** across the complete owner/consumer change. Source and dependency relationships are recorded in SOURCE.md and the before/after receipts. The final existing refactor-audit collector parsed285 production modules with zero omissions and records189 publication/subscription sites. It finds one declaration each of CoreEvent, CoreEventStream, Subscription and CoreEventMessage. Core modules import no Textual. Lexical AST is not dynamic resolution proof; the native lifetime/dispatch checks and installed journey supply the affected behavior evidence.

### Installed acceptance

The released existing302 candidate was refreshed normally through frozen uv dependencies:69 packages, Core992a4311, Textual940880e1, SDK0.12.1 and trusted native960. Every installed Toad Python source byte matches tested production `e2170d93`. No new checkout, environment, native copy or public default publication.

- Existing installed real Toad/ACP/owner/Pi runner: **PASS**,10.368s affected journey, two controlled localhost responses. Actual Textual Pilot Enter reached native admission; the second input was visibly queued, both native answers painted and committed to saved history, queue cleared and idle returned. Actual configuration chooser, channel opening, tab click return and reconnect retained the original owner, editor document, undo history and unsent draft. Pilot is headless; it is not physical X input.
- Ordinary `toad-comms nra-architecture` through the inactive candidate in isolated `st`/Xvfb: **PASS**,12.771s capture. Original41MB history physically readable, original owner unchanged, zero new ACP protocol errors, no owned process leaks. The actual PNG was personally reviewed. Historical Needs-attention/tool-error/read-position-reset facts remain visible; this is not a whole-UX/performance claim.
- FieldCodec and generic carrier/lifetime checks passed at their recorded source scope, including21 expanded family forms without importing Textual. Package/runtime/native preflight passed before physical launch.

Canonical receipt: `evidence/headless-core-events-u1-20261002/READY.json`.
Native receipt: `evidence/headless-core-events-u1-20261002/native06/native-events-receipt.json`.
Physical receipt/pixels: `/home/ts/.cache/agent-scratch/u341-saved-startup-20261002/capture/receipt.json`, `before.png`, `after.png`.

### Preserved failures and limits

Installed01/02 found two omitted consumers: SessionDetails still named the deleted activity Message; activation still called a deleted forwarding method. Both are fixed through the original owners.01 failed before native fixture creation;02 made0 provider requests.03/04/05 retain original failures: stale driver queue API, default loopback heuristic returning IGNORE, and a string comparison against the correct nominal ThinkingLevel. Final06 uses current owner APIs and explicit controlled answers. No old input was replayed; every native attempt has its own retained private root. Native SVG ANSI text exported black-on-black; it is retained as unsuitable pixel evidence, while compositor text assertions and the separate physical PNG are qualified distinctly. The initial invalid Git revision install and miscalled stage preflight are preserved as tooling failures; final source/trust verification passed.

No public prompt, paid provider, authentication change, native owner restart or default publication was performed. Original saved sessions, UNKNOWN inputs and all negative/positive receipts remain protected. Existing baseline-invalid synthetic fixtures are documented rather than claimed passing. CI deferred under owner instructions. U2 and new frontend implementations remain unfinished.
