# Read-only private native history provenance

This isolated consumer is independent of the exact-ID queue project. It never
changes queues, drafts, input disposition, ACKs, permits, retries, or historical
inputs. No live deployment or activation is part of this change.

## Frozen producer contract

Backend: `78f7309fe5753b05e4a8a4d2d15e55d79f658dd5`.

- `docs/private_native_cursor_acp_v1.md`: SHA256
  `b009a404759c11b486b86eca5c78f4407a82f8088c82ecd2c746c472b529fba9`
- Exact copied `tests/fixtures/private_native_cursor_v1.json`: SHA256
  `f8a1f2d8ae27660a643f4687ad7b774343a3fde543eaa493d5bacaa0c8937bc6`

Older `9b30004`, `6889a31`, and `f94fc46` fixtures are insufficient for sink acceptance.

## Consumer boundaries

`private_native_cursor.py` is a pure reducer/parser. It retains only scope,
revision, status and a digest of validated metadata, not private proof payloads.
The parser caps each envelope at 16 KiB; the reducer retains at most 32
pre-response receipts and 32 scope-only epoch floors. These floors survive
superseding requests that clear an uncertain receipt buffer, so even an
initially unbound attachment cannot revive stale proof after malformed input
or overflow arrives before a delayed response. No disk/network/provider operations occur in either.

If 32 *distinct* floor identities saturate this bound, the next distinct scope
cannot safely be forgotten. A sticky evidence-loss fence keeps this Agent
unavailable even across explicit loads; only a fresh Agent attachment resets
it. This intentionally conservative failure is distinct from ordinary
same-key receipt overflow, which retains its floor and can recover on a later
explicit load. There is no automatic reconnect/retry to bypass either fence.

Only actual Agent `acp_new_session` / `acp_load_session` results bind. A request
initiation token fences Agent session/metadata mutation before reducer binding,
not just the reducer's result application. Load also captures its requested
session; stop invalidates any in-flight token. Callbacks
can invalidate but never bind. During an in-flight load, callbacks are buffered;
a newer same-owner epoch establishes only an invalidation floor. A delayed lower
epoch result cannot clear it. Ambiguity, malformed metadata or overflow requires
an explicit load initiated after the uncertainty. Same-scope revisions cannot
regress, even through trusted results. A replacement scope may reset revisions.

Same logical key plus a newer epoch hides incumbent proof. Different creation
identity or same-epoch conflicting PID quarantines without timestamp ordering.
Unrelated logical keys and lower epochs are ignored. Quarantine rejects all
callbacks until a qualifying explicit trusted result. Null-scope/malformed data
never indicates proof or no work. Ordinary events without cursor metadata are
not cursor events; absent cursor metadata on trusted results is unavailable or
hidden. Agent EOF/stop invalidates provenance; replacement Agents clear the row.

The backend proxy's automatic reconnect does not forward trusted cursor-ready
metadata. Thus automatic reconnect cannot clear quarantine. There is no new
callback trust marker, refresh action or automatic load/retry here.

`PrivateNativeCursorUpdate` carries only presentation status plus local
Agent/session/sequence provenance. Conversation rejects retired Agent, foreign
session and out-of-order presentation receipts. Batched delivery does not read
mutable producer state to reconstruct earlier events. NativeHistory is a
nonfocusable, markup-disabled Static row separate from input delivery/queue UI.
It displays only these constants:

- `Native history: selected source proof available`
- `Native history: source coverage only (no injected input)`
- `Native history: no current-owner cursor`
- `Native history: unavailable`

Tooltip: `Read-only provenance, not input acceptance, consumption, completion or ACK.`
No IDs, paths, raw metadata, private source content, or controls are rendered.

## Provider-free acceptance

With a Python 3.14 Toad dependency environment and compatible backend imports:

```sh
PYTHONPATH=src python tests/test_private_native_cursor.py
PYTHONPATH="$PWD/src:$PWD/tests:/path/to/backend/src" \
  CURSOR_EVIDENCE_DIR=/tmp/cursor-evidence python tests/private_native_cursor_pilot.py
PYTHONPATH="$PWD/src:$PWD/tests:/path/to/backend/src" python tests/private_native_cursor_request_pilot.py
PYTHONPATH="$PWD/src:$PWD/tests:/path/to/backend/src" python tests/mcp_live_status_pilot.py
```

The mounted pilot uses actual Agent new/load and validated callback methods,
real Conversation message delivery, and compositor-visible row assertions. It
mocks only ACP response transport, never calls a provider, and uses temporary
XDG/wire roots. It checks canonical pre/postbind sequences, all labels, batching,
revision/conflict/foreign/retired fencing, overflow, malformed/null metadata,
stop, private-data absence in SVG, and unchanged queue/draft/input state.

Owner evidence: `/dev/shm/toad-cursor-f94-owner/` (initial unit/mounted/MCP logs
and SVGs); `/dev/shm/toad-cursor-floor-fix-owner/` adds the independently found
superseded-request floor-loss regressions, including genuinely overlapping
Agent load calls in the mounted pilot. Initial head `0675cf7` was held after
independent review found that blocker; it is not a cleared sink freeze.
`/dev/shm/toad-cursor-request-fix-owner/` adds actual mounted overlapping
new/new, load/new, new/stop and load/stop request fencing regressions and a
prebind-null poison case. Independent review also found that a stale new result
could relabel successor proof by mutating Agent.session_id before reducer token
rejection; Agent-level result fencing fixes this separate blocker.
Latest evidence `/var/tmp/toad-cursor-78f-owner/` includes canonical 78f null
prebind and distinct-floor saturation controls (14 pure tests plus mounted
provenance, mounted request-fence and adjacent MCP pilots). `/dev/shm` reached
its write quota during the final run; the successful rerun uses `/var/tmp`.
The older `prompt_queue_pilot.py` times out awaiting its stub response at line111
both on this consumer and unchanged base `b6220b7`; logs `queue.log` and
`queue-baseline.log`. This is not a queue acceptance verdict. Existing unresolved
queue ordering work remains on its separate branch.

These are deterministic fixtures, not a live ghost trace or proof that any
native input was accepted, consumed, completed or acknowledged. Independent
review of the frozen consumer is required separately from backend review.
