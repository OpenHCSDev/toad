# Continuous input visibility

Owner: Kepler. Base: Toad `19970f56899674932584138ff5e6fbe533c4af8f`.

## Report and acceptance

A successful send can disappear from both queue and chat before its native
user message appears. Preserve one visible original input throughout submission,
authoritative acceptance, queue residence, native start and user-message paint.
Before acknowledgment show the outstanding submission honestly. An accepted
input stays visible in the queue until its actual native user message paints.
Never manufacture a backend queued fact or retry an uncertain input.
Refusal, UNKNOWN and cancellation retain their original dispositions.

## Ownership and crossings

Kepler owns ConversationSubmissions, Prompt submission/queue rendering and
Conversation submission/queue/start/failure/disposition consumers. Heisenberg
owns history, binding, viewport, workspace restoration and sidebar performance
in PR249. Changes to his consumers require direct handoff. Mendel owns the
backend input/coordination builder in Core457; Arendt owns native admission in
Core456. Request missing capabilities from those declaration owners.

The local SubmissionExecution is the real outstanding request resource;
QueueAttachment owns the decoded producer projection. Native input identity,
admission and source proof remain backend owned. No parallel receipt store,
status flags, seen list, optimistic queue or synthetic transcript message.
Applicable NRA patterns: IDEN-5 (a fact split across stores), BOUND-2 (bypassing
the decoded owner), IMPL-12 (drifting copies of one procedure).

## Initial source witnesses

ConversationSubmissions.publish_pending already invalidates Prompt's queue
view. Only ImmediateInputSubmission currently supplies pending_text;
ordinary/deferred requests return an empty string, so the original outstanding
request is omitted from the prompt projection. This is a source observation,
not yet the complete cause or live acceptance evidence. Trace producer queue
acknowledgment and native input/message publication before choosing closure.

## Actual journey

Reuse the existing installed first-input/native ACP UI fixture with controlled
provider responses only. Observe real submission and clicks, authoritative
acceptance, queued pending, native start/user paint, reply and completion. Assert
the original input is never absent from both queue and chat and is painted once;
include original cancel/refusal/UNKNOWN dispositions. Record exact candidate
pins, physical frames, cleanup and deleted lines. Source checks alone are not
Ready. No public-owner replay, restart or provider duplicate.

## Working checkpoint

Core457 `7f64d7ac0b72a8a2a7be373cf1ddb045a86dcaad` supplies the original
PromptRequest.input_id. The same request object is held by SubmissionExecution
and encoded at ACP ingress. Its accepted queue row and native-start receipt
join by that identity, never by equal text or arrival order.

The local outstanding request displays Submitting only while neither its
canonical accepted queue row nor its actual received native-start receipt owns
the input. The execution retains the same typed receipt after native mounting
until the real RPC finishes; this resource cannot authorize a retry. Removing
the idle-turn reset leaves request retirement with its original finally/finish.

Native user mounting and queue invalidation share the existing HistoryWindow
publication transaction. UserInput holds a source-backed commit claim instead
of a separately copied native_id. StartedInputClaim retains the original start
fact; TranscriptInputClaim retains the original saved UserTranscript. Their
shared NativeInputClaim owns source coverage. The saved-history constructor and
its native installed consumer migrate in place, with no alias or fallback.

The frozen250 first-fork failure is preserved at
`/home/ts/wt/g458e/u01/proof/terminal-receipt.json` and
`/home/ts/wt/g458e/ui-firstinput01.log`: native answer once, mounted/painted
answer twice. Heisenberg owns that live/snapshot publication defect in PR252;
the affected continuous gate must cover both exact-once input and answer.

Status: source checkpoint, not Ready or live. One existing declaration-family
test passed; changed production parses and diff whitespace checks passed.
The checked-in dependency now uses coherent Core458
`d12f2d87e0c9d2b85f9aa6147c1eb659133e3dae`, including456/457/460. Its production
source is identical to the later guard/documentation checkpoint c01dab4d.
The installed continuous native gate remains required.

## Queue-to-native paint and continuous driver

The producer retains an accepted row during awaited Started publication. Prompt
derives its visible queued rows from the original producer rows and mounted
source claims: a StartedInputClaim identifies the same original request, so
that retained row cannot appear again beside its native UserInput. Queue control
authority stays with QueueAttachment. No retained seen list or copied status
is introduced. This is a rare queue invalidation projection, not a per-frame
history scan.

`tests/input_visibility_native_installed_pilot.py` extends the existing installed
first-fork journey rather than replacing its failed exact-once answer oracle.
The actual application, ACP worker, Pi owner and private retained source remain
real; only the provider response is controlled. The extended journey submits a
busy turn, accepts a follow-up, clicks Send now, verifies its original native
user once, and cancels a further original input after native start. A five-call
local fixture budget prevents replay. UNKNOWN/refusal UI acceptance is not yet
claimed by these added cases.

The observer records original incremental compositor updates and typed original
request/queue/Started sources. It never requests a full render or manufactures
protocol facts. Offline terminal replay must find each outstanding original
input once in submitting/queue/chat through its first native paint. Subsequent
frames still reject a second occurrence after that handoff; retirement to saved
history must not resurrect the accepted queue row alongside the same user text.
These are offline measurement records, never application state. The terminal
driver and headless flag are recorded explicitly. Headless output is compositor
evidence, not a physical-terminal readiness claim. Use the existing PTY driver
with `INPUT_VISIBILITY_TERMINAL=1` for native terminal output; `pyte` is an existing
development dependency for offline review. No extra paid provider calls.

Deleted obsolete pilots: send_status (170 lines), send_now_failure (48 lines),
queue_manage (85 lines), totaling 303 lines. They populated removed status/queue
mirrors or patched transport replies. The real boundary pilot and manual journey
helpers instead consume ConversationSubmissions in place. Historical receipts
that mention these pilots remain preserved. No removed API is restored.

Source checks: existing family test passed, typed frame FieldCodec round-trip
passed, changed Python parses passed. No new UI/native capture has been run.
Parent owns integration with249 and caller250; Heisenberg owns252 response
publication. Run one new continuous paired candidate after substantial252 source
is ready; never rerun the unchanged frozen250 candidate to hide its failure.

## First combined run: retained target and paint-clock correction

Einstein's `g458f/u01` real LinuxDriver journey passed the inherited first-fork
oracle: one original child input and answer, one mounted and painted answer,
and one tab/process attachment. It then failed `pilot.click(SendNow)` after an
accepted follow-up. All three local provider requests and raw evidence are
preserved at `/home/ts/wt/g458f/u01/proof`; no old action is replayed.

The final original terminal stream shows the global Toad menu opening while
the child's queue and Send now control remain visible. Textual Pilot resolves
a class target with `screen.query_one`, allowing the retained hidden parent's
control to win. The corrected driver selects the original current Conversation's
Prompt control, requires actual nonempty hit-testable geometry, records its
owner/region alongside the global lookup, and performs the same real click.
The assertion remains strict. No queue state/control method replaces the click.

The old observer also counted status captions across the entire screen as input
messages. New recordings include the original native queue-label and chat-window
regions. Review covers those physical regions exclusively. In u01 frame111 the
local beta request existed before its first presentation paint at frame112,
20,019,172ns later; a source resource is not an already-painted UI frame.
Review measures source-to-first-paint latency. Once the original input appears,
every frame through first native user paint must contain it once; later frames
must not duplicate it. This preserves the queue-to-native no-gap obligation
without demanding simultaneous asynchronous receipt and paint. Old raw/schema
and failed review are preserved, not rewritten using new geometry guesses.

This correction is tooling only. Product source remains frozen; Einstein owns
the sole fresh affected journey using original owned resources and a new private
fixture. Pending/UNKNOWN dispositions from u01 are not replayed. Until that
queue/control journey passes, the combined candidate is not whole-workflow Ready.
