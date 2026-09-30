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

## Candidate checkpoint

Production now consumes Core #430's original `MessageReference` source for both
incoming and outgoing bodies. One `WireMessageHandling` capability joins original
target notifications through the existing canonical read service. Removed
`AssignedInboundPublication`, `AssignedIncomingMessage` and all consumers, plus
the obsolete 192-line synthetic native-input attribution pilot. No private seen
registry or imperative notification-tail repair remains.

The installed three-window native04 journey proved original channel send hot in
the already-open sender DM, recipient DM and IRC; target Responding while both
provider continuations were held, and target Responded in all three views after
release. Distinct reply source identities appeared in both DMs. That run exited
1 at an exact body-count assertion executed 300ms after turn completion; it did
not record the count or prove paint completion. It therefore does not establish
reply duplication or a passing once-only gate. No speculative backend filter was
added. Its original wire and ACP logs are preserved in owned scratch.

The next fixture waits for physical response paint, records the exact mounted
body count/source/resource parent, and preserves the whole original coordinator
and selected native journals before fixture disposal. The prior selected journal
was not `registration.session_file`; that incomplete evidence is explicitly
acknowledged. Each rerun is a new isolated fixture, never a replay of live input.

Normal merged viewport #214 integration is complete. Required ratchet against
that main passed with no positive debt deltas. Current production removes 95
lines and adds 188 relative to this main (including the shared canonical capture
capability from #218). Source checks do not replace the outstanding installed
physical-paint/once/return acceptance.

Status: draft; useful hot publication is verified but the complete affected
installed journey is still pending. Not merged, installed globally or live.
