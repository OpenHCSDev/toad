# Read-only native-history provenance view (planned companion slice)

This is a separately frozen slice from queue identity projection. Current Toad
has no privateNativeCursor consumer. The reported delayed-update counterexample
establishes stale ACP metadata delivery, not an observed Toad paint regression.
No consumer may be wired before the backend owner supplies the exact trusted
all-status scope/revision contract, fixtures, and frozen implementation SHA.

## Minimal agreed surface

A separate read-only session-provenance row, not the queue summary or transcript.
No source content, filesystem paths, or actions are shown.

| Backend status | Display |
| --- | --- |
| `proven` | Native history: selected source proof available |
| `coverage_only` | Native history: source coverage only (no injected input) |
| `none` | Native history: no current-owner cursor |
| `unavailable` | Native history: unavailable |

Tooltip: **Read-only provenance, not input acceptance, consumption, completion
or ACK.** Unsupported or absent metadata is hidden/unavailable, never inferred
proven. `coverage_only` has a proven source-coverage cursor; it must not be
mislabelled as absence of cursor proof.

## Pending backend freeze and separate acceptance

- Trusted new/load/reconnect result establishes owner-incarnation binding and
  per-session projection revision for every status, including none/unavailable.
- Notifications cannot adopt a different owner. Older revisions and retired
  Agent/session events are rejected again when the mounted UI consumes them.
- A delayed older-owner proven update must not overwrite a newer trusted-load
  none snapshot. Same-owner revision reorder and batched events need independent
  positive and negative coverage, not only per-notification queue draining.
- Cursor state never mutates queue membership, input disposition, UNKNOWN state,
  ACK, retry, or replay controls. Queue and cursor test results remain distinct.
- Tests use disposable provider-free fixtures; no installed/live mutation or
  activation, and no replay of any historic input.
