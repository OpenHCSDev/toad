# Read-only exact-ID queue consumer

This supersedes the implementation proposals in `queue-view-contract.md`.
Cursor PR63 is independently merged at `66cb3f9b03b49b4bd8d89aa87ba5864a3d19c00a`;
queue acceptance is separate and still requires an independent exact-head review.
No installed/live activation, backend edits, mutation API, replay or retry.

## Pinned contract

Producer: `79cd5a8c7254bfcddd8d07c9525076c3e78f1a20`.
The unmodified copies are `acp_exact_id_queue_v1.md` (SHA256
`e0b9ea81e4b3e986822bbd6ac235d7571465ad0b6240dffb4711373a441ca87f`)
and `tests/fixtures/acp_exact_id_queue_v1.json` (SHA256
`cffc19837f6f013fba561e7a77197a8aab944b6fc2e617522dcb1bfe19c8f2de`).

## Presentation boundary

- Actual trusted Agent new/load results alone establish a binding. Callback
  binding fields and automatic reconnect configuration never establish one.
- Scope includes attachment session, owner name/creation equality, admission
  epoch/generation. Alias translation changes only the attachment session.
- Ordered items/restored retain opaque exact IDs; equal text remains distinct.
  Higher-revision exact starts remove only their ID and echo at most once.
  Lower revisions, contradictory equal revisions, duplicate starts and old
  scopes cannot mutate current rows. Authoritative snapshots can remove rows
  without claiming acceptance, consumption, completion or ACK.
- Null/malformed/oversized state means **unavailable**, never an empty queue.
  Newer/ambiguous scopes quarantine; only a later explicit load can recover.
  Validated higher epoch floors survive request supersession, uncertainty and
  quarantine. Source Agent/session/sequence fences and remount snapshots keep
  delayed UI receipts from reviving obsolete rows.
- Restored rows are read-only, not composer drafts. Server failure notices and
  legacy text-only queue callbacks cannot inject remote text into the composer.
  A local request failure can recover its own text only while its originating
  Agent/session/queue owner remains current. No text-matched remote removal.
- Prompt summary paints authoritative counts/previews and read-only restored
  rows, or an explicit unavailable label. Send-request feedback does not hide
  a queued row. No optimistic local submission is treated as remote membership.
  Edit/remove/reorder/clear-and-resend controls remain unavailable.

Parser bounds: 32 rows across items/restored, 4096 UTF-8 bytes per text, 65536
aggregate text bytes, positive signed-63-bit revisions/epochs, at most 1024
characters/4096 UTF-8 bytes per opaque identifier. Only normalized immutable
known fields are retained or compared; extra metadata is not serialized or
traversed. Prebind receipts and floor identities are bounded at 32. Distinct
floor exhaustion or 4096 exact-start tombstones causes sticky unavailable on
that Agent; only a genuinely fresh Agent resets evidence loss. Same-key
receipt overflow can recover via a later load without losing epoch floors.

## Provider-free reproduction

Use the normal Toad test dependency runtime (Python 3.14) and an archive of the
pinned backend, not its mutable worktree or an installed package:

```sh
mkdir -p /var/tmp/toad-queue-backend-79cd5a8
git -C /path/to/comms-repo archive 79cd5a8c7254bfcddd8d07c9525076c3e78f1a20 src \
  | tar -x -C /var/tmp/toad-queue-backend-79cd5a8
export PYTHONPATH="$PWD/src:$PWD/tests:/var/tmp/toad-queue-backend-79cd5a8/src"
export QUEUE_EVIDENCE_DIR=/var/tmp/toad-queue-evidence
PY=/tmp/opencode/toad-fork/.venv/bin/python
"$PY" -m unittest discover -s tests -p test_queue_view.py -v
"$PY" tests/queue_view_pilot.py
"$PY" tests/queue_view_request_pilot.py
"$PY" tests/queue_view_backend_pilot.py
```

The canonical mounted pilot uses the complete canonical fixture and real
Agent/Conversation/Prompt methods. The request pilot covers new/new, load/new,
new/stop, load/stop and delayed retired Agent/owner draft recovery.

The integrated pilot checks exact producer ACP/runtime source hashes, bridges
actual producer new/load/prompt/emission to actual consumer RPC methods, and
asserts compositor-visible summary text and screenshots. It exercises two
identical-text admissions, one exact start, repeated/out-of-order receipts,
read-only restoration, actual proxy alias mapping, reconnect/rebase, and real
ACP `userText='\ud800'` ingress returning a null but attachable projection while
its queued ID and durable UNKNOWN survive. Old-admission rows and UNKNOWN
remain in backend state after the new owner's authoritative empty snapshot.

Transport, native event generation, model discovery and background live drain
are provider-free fixtures. In particular synthetic `input_started` is **not**
a native consumption receipt. This is not a Unix-socket reconnect or live
provider/root-cause test. Cursor, queue reducer, mounted sink and integrated
producer/sink evidence have separate acceptance boundaries.
