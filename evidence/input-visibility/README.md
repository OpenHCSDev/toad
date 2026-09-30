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
Coherent Core458 integration of457/456/460 and the installed continuous native
gate are still required. The checked-in dependency remains the base pin until
the integration owner supplies that coherent artifact.
