# Published owner turn status

Actual default helper493 replied494; retained after-state sidebar source has
no active lease, matching finished turn05d3c93ed7920eab91b71b87fdb46826 and
idle observed activity. The physical chat simultaneously retains Waiting for
input start. Original ACP log admits that active turn but records no terminal
notification before capture. No493 replay, public mutation or recovery.

Existing declaration/consumer family:AgentController prompt operation lifetime,
ManagedTurnBinding/TurnOwner, CommsUpdateConsumer/OwnerSnapshotConsumer,
ConversationTurn, TurnActivity, Prompt, SessionDetails; queue/input and cursor
have separate original proof owners. Snapshot settlement must not overtake a
client-owned ordered prompt response. A remotely initiated turn does not imply
that this frontend owns such a response. Trace and fix that distinction through
the existing controller/consumer capability; do not patch labels or copy status.

Source and AST first. Read full related declaration/consumer paths, reuse existing
owners, delete displaced stream-vs-turn decisions together. Final validation
uses a proportionate installed continuous client/saved-source path, not a new
provider experiment. Original493/capture/readback, current default and other
agents' sources remain untouched. Same persistent checkout/environment; CI deferred.

Backend native input/cursor facts are coordinated directly with Mendel. Cursor
unavailable is not an input disposition and will not be made proven from a reply.

## Working ownership closure

Removed OrderedManagedTurn and accepts_snapshot: a busy remote turn never
proved that this client had an ordered response outstanding. ManagedTurnBinding
now receives the original TurnState through one ManagedTurn projection.
OwnerSnapshotConsumer receives both original goal metadata and the original
ThreadPresentation.read_identity.thread.turn_state. It preserves session, root,
incarnation, finished-turn matching and emission-sequence fences.

AgentController.prompt_in_flight remains the original local operation resource,
not another backend status. Its shared owned-task lifetime covers text, blocks,
send-now and manual compaction, including failed/cancelled requests. Once the
last operation releases custody, the existing AgentProcess owns a fresh guarded
read of the same source. No snapshot cache, pending flag, timer, extra RPC or
per-widget phase decision is introduced. Retired reads establish no settlement.

QueueAttachment still consumes the producer's queue/start receipts; its bounded
prebind resources and last-start revision fence prevent repeated input paint.
ProjectionAttachment still requires the original cursor envelope/scope/digest.
InputDocument/InputAttempt owns human delivery, NativeRuntimeInput owns managed
execution. No HumanInputDocument for493 is legitimate, not missing native proof.
Mendel's read-only current-scope check found no current-admission cursor row;
Responded is not cursor proof. SessionDetails' bus-verification warning is thus
kept separate from the stale turn phase. Original captured unavailable cursor
189/190 is preserved; its acquisition failure cause is not established here.

Patterns: IDEN-1 (two meanings of busy), IMPL-12 (request custody repeated or
bypassed), TIME-6 (delete the replaced decision). Semantic source analysis is
complete before validation; lexical AST includes dynamic ambiguity explicitly.
