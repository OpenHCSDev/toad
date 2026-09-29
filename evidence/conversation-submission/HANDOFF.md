# T4 Conversation submission lifecycle

## Ownership and deletion

Base: main5059d4aa (167 configuration owner preserved by normal merge). Original T4 dispatch remeasured on current source; scope is Conversation's remaining shared input transaction, not App/source retention or Agent process reimplementation. Tesla160/Noether166 claims posted before source changes; no peer tree edited.

184 old production lines deleted:178 in Conversation (send closure, empty/shell/queue/immediate switch, request-bound scope checks, string pending input-ID),6 ACP signature/flag decoder lines. All actual callers of `send_prompt_to_agent`, `send_queued_now`, `_sending_queue_input_id` and delivery/defer keyword API migrated; existing deletion guard now forbids the retired names.

`InputSubmission` is a public abstract declaration family; empty/queue-now/shell/ordinary/deferred/immediate cases own hooks and inherit shared agent execution/feedback. Family membership derives from declarations. `SubmissionExecution` owns captured Agent/session/queue authority and the actual typed core PromptRequest; `ConversationSubmissions` owns outstanding local requests, exact QueueItem scheduling indicator and idempotent local draft recovery. Remote membership remains solely QueueAttachment; no remote edit/replay/delete-by-text. Existing Conversation reactive strings are display projections. QueueAttachment owns original request admissibility. CommsChat retains its intentional independent override of the same submission boundary.

New-case edit count: previously a new intent edited central flag selection and send flag translation; now one declaration inherits execute/request/feedback and joins the derived selector. `test_conversation_submission.py` proves this with a declaration-only new case and no selector/caller edits. No legacy alias, parallel queue store, codec or workspace lifecycle introduced.

Reread current NRA, exact resolved archive audit skill, pattern README, implementation/identity/membership catalogs. Applied IMPL-4/5/8, IDEN-1/3, MEMB-1 and BOUND-1/2: behavior on declarations, captured request identity, shared queue authority, typed request boundary. ownership.json records per-file absence/chain/class excess; none increases, no new owner crosses500. Conversation and ACP Agent shrink; no claim that all T4 is complete.

## Actual evidence

Noneditable own candidate installed into `/home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed`. Actual core35648868e6d, Textual1738abd8, native d3967e8b. No paid calls/live state mutation.

- `attachment.log`: mounted new/load successor, stop, replaced Agent/owner/quarantined queue cannot restore old text into successor draft.
- `input-failure.log`: mounted real ACP error catch and local exact draft recovery; remote failure evidence remains read-only.
- `send-now-failure.log`: rejected real ACP boundary clears indicator while retaining instruction.
- `declaration.log`:1PASS declaration-only inherited new case.
- `deletion.log`:2PASS existing deletion/environment guards.
- `native.log`: exit0 continuous installed normalApp/Pilot→real ACP→Pi localhost-provider journey: physical Enter saved reply, reconnect saved paint, physical ordinary held input, physical deferred input exact queue membership, blank Ctrl+y Send now, durable queued input bound/consumed, NATIVE_RESPONSE_3 painted, channel/source return retaining same Agent/draft/Document/undo. Exactly3 controlled provider requests; no fourth replay. `native/submission.svg` captures final viewport. The known interrupted provider response2 may lose its socket because actual Send now interrupts it; the fixture permits only that specifically selected request number to disconnect, preserving all other provider errors.

Command (parent substitute paired candidate python/native if needed):

```sh
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent \
L0A_EVIDENCE="$PWD/evidence/conversation-submission/native" TMPDIR="$PWD/.artifacts" PYTHONPATH="$PWD/tests" \
PATH="/home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin:$PATH" \
timeout 60s /home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin/python tests/submission_native_installed_pilot.py
```

Retained RED receipts identify test corrections: transient already-cleared pending indicator, obsolete app test caller, controlled interrupt's expected socket disconnect. Product behavior passed before those harness corrections; no failure suppressed beyond expected disconnected response2. Native private roots/processes retired by existing fixture; owned .artifacts empty. No live activation or current parent-pair gate claimed: parent owns those. CI deferred. Whole-shell/immediate-text matrix not claimed; shared typed case inheritance/source behavior exercised by declaration check and native queue journey.
