# Canonical wire conversation publication

Integration owner: Schrodinger. Depends on reviewed Core #430 and Toad #210.
Mendel owns durable wire source direction, original message identity, recipient
assignment/execution outcomes and the canonical transcript read identity.
This frontend scope owns continuous DM/IRC publication through existing source
and presentation owners. Arendt owns backend turn and input lifecycle; Heisenberg
owns retained body and reader policy. Coordinate those shared methods directly.

Concrete failing journey: both sender and recipient tabs are already open. A
sender emits a DM, which appears in IRC but the sender DM updates only after
reopening. Its original outbound row has no target handling; handling on the
incoming reply describes a different original wire identity.

Close the whole source relation (IDEN-5, IDEN-6, TIME-9): remove synthetic
AssignedInboundPublication/AssignedIncomingMessage append and all consumers.
Original durable wire records own incoming/outgoing direction and chronology.
Canonical source read identity changes trigger existing publication even when
native bytes and wire sequence do not change. Update prepared/rendered source
fragments and handling through their original MessageReference and frozen target
identity. No seen list, revision mirror, inferred read acknowledgment or second
message store. Reader position, draft, undo and bounded warm resources remain.

Acceptance: actual installed native/ACP/UI controlled-localhost journey with
both DM views and IRC open before sending; original outbound, received input,
notice/processing/handled transitions appear without reopen or selection.
Include an older original outside the recent-five window, same-frontier handling,
cold reopen/A/B/A, one row per wire identity, preserved chronological placement
and no duplicated provider inputs. Ship a useful checkpoint after this journey;
performance polish remains independently owned.

Status: draft scope opened before long implementation; no readiness claim.
