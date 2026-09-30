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

Status: draft opened before implementation; producer/consumer tracing underway.
