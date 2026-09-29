# T4 Tool output ownership — ready for parent review

Source00d016e includes current main144/4147eb1. Parent owns merge/live activation.
No own-scope blocker remains; CI deferred. Actual installed provenance is in
installed.json: Toad wheel from this own persistent tree, core306 b77db612 and
Textual8 c9743801. Parent is independently staging newer core311; this receipt
claims the current Toad main dependency pin, not an untested newer deployment.

## Implementation and deletion

ToolCall AST469 →235; ToolCallDiff136 →135. ToolOutput owns mounted content,
serialization, lazy hydration and background preparation custody. Declared
ToolOutputPart cases own rendering, retained updates, preview and preparation/
retirement. Membership derives from the existing core DeclaredFamily. Literal
text is LiteralTextToolOutputPart, with no generic compatibility path or alias.
Raw ACP input is decoded at presentation admission and explicit updates. This
preserves saved-history producer mutation before first mount, captures subsequent
mutable adapter updates, and includes Read filename/kind in presentation identity.

Delete root content dispatch/classifier, raw snapshots, lock, cache/worker fields,
warmup/hydration helpers, dead ToolCallItem and standalone demo. Migrate every
actual moved-widget import. Private hidden renderer/cache goldens are deleted;
controlled lifetime and historical foreground-read substitution are replaced by
real rendering behavior. No Conversation/Agent/workspace/shell/read ACK edits.

New text case: one declared SpecificTextToolOutputPart subclass, zero root,
classifier inventory, registry, scheduler or retirement edits. The installed
new-case guard mounts/paints/collapses/reopens such a declaration. Root keeps
Textual handlers, header/expansion intent and existing viewport participation.
The adjacent existing permission-only ACPToolCallContent raw preview stays in
Carver's Conversation/permission surface, whose presentation policy is distinct;
it is not restored as a second ToolCall output path.

## Verified affected paths

- native-main-reviewed.txt (1 passed18.46s): actual installed Pi executes Read,
  Edit and Bash in a private project via real native journal/owner/ACP transport.
  Real worker highlighting, diff counts, cropped viewport paint, exact copied
  text, ANSI spans/escape removal, collapse/reopen. Only the model response is a
  deterministic loopback fixture; no provider calls or live state mutation.
- cancellation-reviewed.txt (1 passed7.55s): actual installed renderer hidden
  preparation/reveal, replacement, theme, collapse/reopen, child and whole-tool
  remount/retirement; real Textual cancellation before entry + GC has no unawaited
  coroutine warning. Worker submissions use supported async partial/callables.
- current-main.txt: 3 affected guard/retained checks passed; its native failure was
  a fixture frontend-status wait race, corrected and independently passed above.
- focused-final.txt: 7 passed, one new copy expectation incorrectly included
  terminal newline. selection-final.txt then passed the corrected Textual
  SELECT_ALL contract while separately asserting complete source text. The
  corrected current-main retained check passed too. No aborted/full suite claim.
- Diff live/replay, sparse high offsets, blank-tail, malformed patch selection,
  large explicit expansion, lazy histories/offscreen hydration and actual Read
  preparation performance passed in affected local runs. Diagnostics retain
  original failures rather than hiding them. No unchanged64 workspace rerun.

Independent installed ratchet ratchet-final.txt has zero positive class/debt
measures; new owners have no baseline until their first merge, not fabricated0.
Source diff:614 added483 deleted; behavior moves into declared state owners,
with frozen cases/shared capabilities instead of five repeated decisions. Test
coverage adds real native/extension behavior while deleting private cache/control
implementations; exact line counts are recorded in the PR.

## NRA coverage and limits

nra-final.json.gz is the exact raw R1 receipt: all709 discovered Python production
files (234Toad,226core,249Textual); parse2.672s + analysis47.29s, exit0 within120s.
30 raw/30 aggregate findings; five owned projections are the unchanged ACP
status/header literals matching broad shared-family vocabulary. No raw output
owner/diff-widget finding was emitted. These structural overlaps are not native
or runtime proof. CLI exposes no scan_status or analyzed/omitted detector counts;
none are invented. nra-scope.json retains the relevant projections/limitations.
The earlier baseline excludes Textual; final complete audit includes it, so raw
finding totals are not a valid before/after comparison. Ownership/custody changes
are authored semantic patches, not claimed as an NRA-proved DSL transaction.

Owned disposable scan snapshot, raw JSON superseded by compressed receipts and
inactive attested failed-test roots are removed; source/commits/predecessors are
preserved. cleanup.json records the boundary. No live changes or paid calls.
