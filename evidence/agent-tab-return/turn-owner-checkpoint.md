# Turn owner checkpoint, 2026-09-29

## Current ownership and delivery

PR #194 remains a draft candidate. The default live runtime does not contain it.
The candidate pins core #401 (summary publication) and Textual #12 (computed
observer notification), both merged. Activation follows actual user-path checks.

The Agent alone owns its managed `TurnOwner`, including activity and elapsed-time
origin. `AgentPresentation` declares a local or managed `TurnBinding`; the shared
Conversation retains one stable binding across source changes. Activity, Prompt,
its editor and ObservedThrobber read the owner directly. The old writable
turn-owner and prompt-busy projections were deleted. Local work retains its own
count and contributes to the indicator without settling a managed turn.

Observed thread reads bind to their actual Agent. Switching sources or settling
a turn retires the previous read and queued observations, so they cannot repaint
the newly selected source. The existing SessionDetails disclosure reads the same
turn owner while busy. The Contents lookup names its owned `#contents` element;
the former class-only lookup also matched Collapsible's different Contents class.

Throbber animation derives its default interval from Textual's frame declaration,
and accepts an explicit `refresh_interval` override. Its shared paint/timer
implementation is inherited by ObservedThrobber. Warm history remains bounded
by the existing byte and widget budgets; the redundant fixed body-count limit
was deleted.

Reviewed against the current NRA skill and the entire refactor-audit pattern
catalog: declaration-owned behavior, no managed state mirrors, no copied frame
default, one computed notification implementation (IMPL-13), and deletion in place.

## Verified boundaries

- The installed candidate's continuous two-native-history A/B/A journey passed
  with actual editor clicks, ACP, Pi and a controlled localhost provider. It
  checked identical retained bodies, zero preparation misses, reader position,
  draft/undo, selected goals, active versus idle sources and settlement. Measured
  selection-to-paint was 171–220 ms. This is a useful checkpoint; sub-50 ms remains
  follow-up work.
- A 2,000-row actual mounted throbber check passed with TEXTUAL_FPS=45 and an
  explicit interval override: stable geometry, scroll and timer, and no idle ticks.
- The actual active-route installed candidate loaded nra-architecture and
  agent-comms-ux and completed idle A/B/A clicks with correct activity, prompt and
  indicator state after the Textual fix.
- Latest paired active-turn and continuous saved-state journeys are pending.

## Failures retained and resolved

Earlier native runs exposed an intermittent blank first frame and the Contents
class collision. Their failing evidence remains recorded; the later stable-binding
native journey passed. An attempted computed-reactive mutation failed because
computed properties are read-only; that mutation was removed. The installed
active-route startup then exposed an infinite GoalBar separator callback loop:
reading unchanged computed busy re-notified the watcher. Textual #12 routes reads
through its existing change-only computed update, deleting the second notification
implementation. Its 31 reactive tests and the actual Toad startup/return check
passed. No failed or uncertain native input was replayed.

Scratch owner: #194 integration; purpose: bounded installed UI/native receipts;
path: /home/ts/.cache/agent-scratch/toad-pr194-turn-20260929. Keep concise receipts
in this evidence directory and remove disposable run files after integration.

Still required before activation: verify the final paired native saved-state
journey, including fast/reverse/idle/End scrolling and no past-end void, then
install and verify the actual default user entrypoint. Large live histories must
be checked separately from the representative two-history fixture.
