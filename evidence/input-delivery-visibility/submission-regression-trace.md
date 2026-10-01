# Submission visibility regression and affected acceptance

The history confirms a loss of existing feedback, not a new queue feature.
Before `3cc8efb327c4bdb9a3e8e31ee50da82105154b72`, ordinary submissions posted
their local `UserInput` before RPC/persistence. Busy deferred submissions were
represented by the backend queue; explicit immediate/send-now captions used
copied local fields. The extracted `AgentInputSubmission.feedback` preserved
that immediate ordinary post, but `pending_text` was empty except for the
ImmediateInputSubmission case.

`f415d6ee47e67a34655a71df0ba886bf09bf7fa7` correctly removed copied queue/turn
fields and routed the ordinary preview through `TurnBinding.present_input`.
ManagedTurnBinding inherits the receipt-only no-op contract: a managed native
user is posted only from a native start receipt. But the old immediate-only
`pending_text` projection remained. An ordinary idle or deferred input now had
neither local chat preview nor a local outstanding-request caption before the
producer's queue/start publication. The same turn refactor retained
`submissions.reset()` on an idle turn publication, which could discard the
outstanding request while native admission was still pending.

251's already published product correction derives Submitting for every real
current managed SubmissionExecution from its one original PromptRequest,
excludes accepted producer rows by that request identity, and removes only the
idle-publication reset. Binding/release retirement remains. No optimistic
managed UserInput, restored pending_text flag or local queue store is added.
Mendel457 separately retains the actual accepted producer queue row through
the original InputStarted publication. UserInput claims carry that receipt;
queue/chat consumers query it instead of a separate seen list.

Actual u02 proves native firstfork/followup/cancel exactly once and the corrected
current-owner SendNow click. Its strict physical oracle remains negative:
old Submitting and new Queued captions coexist until the native compositor
clears the old geometry. Heisenberg owns the causal Textual compositor damage
fix, reviewed Textual PR15 `a5c6678da3873f4a0b3a85dfe876aaa6ffcc8ca3`,
now merged as `6b5895fa0a72aeec2aeaef7206d5debfa0c1803c`. 252 owns the
shared source-publication completion seam. These are one user workflow with
disjoint semantic and raster owners, not a reason to restore mirrors.

The next existing five-POST native journey now uses physical editor Enter for
the parent seed as well as child, busy start, deferred followup and cancel start.
One fixture-only input context holds the root/identity-attested original private
worker via its native pidfd, waits for real emitted Submitting/queue paint with
the original typed request and no native start, and resumes that same worker in
finally. It never changes UI/protocol state, adds an input, or suspends a public
owner. Its canonical input-store lock is acquired nonblocking while held: any
contention fails the attempt through the same worker-resumption finally block,
rather than waiting on a potentially suspended lock owner. The offline raster
oracle requires a pre-delivery caption before each
native user paint as well as no gap/duplicate after first presentation.

The affected driver imports and diff whitespace check pass against the existing
installed candidate. Reprocessing the original u02 emitted ANSI still rejects
the unchanged real duplicate at frame 109, timestamp `278264070472524`, original
request `753f9588872740f29d6dada6d77b7a4b`: two physical captions. No application,
native process or provider call was started for these checks. This is not a
fresh native acceptance claim. Einstein is the sole future
runner after the coherent 467/252/Textual fix is staged; the original failed
u02 recording and initial observer failure are retained unchanged.
