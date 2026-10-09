# Position readers acquire their original path

Physical05 records a 96.39ms full arrangement from TextArea Undo's cursor-region
lookup. That is a position request, not a request to enumerate all descendants.
The recording does not retain the queried widget or explain its viewport miss;
no whole-journey timing reduction is claimed.

Compositor already owns committed scene selection, retained ancestry paths and
explicit complete layout. Two position decisions were competing with it:
completeness invalidation rejected committed full-map coordinates, and missing
positions/membership forced full_map even though only one widget was requested.

Published positions now derive directly from the same original _published_map
used by paint/hit layers. A missing position uses original reflow_visible with
the requested ancestry and existing scene members retained. Membership consumes
that same position acquisition. Explicit full_map enumeration still arranges all
descendants. Recursive measurement and scoped capture keep their original rules.
No additional map, cache, target registry, readiness rule or timer is introduced.

Native layout, scroll, hide/prune/reparent and mutation/capture consumers were
read before editing. Existing Package parsed 249 native production modules,
464 tests and 288 read-only Toad modules, zero omissions; before.json records
881 lexical sites. External dynamic consumers are not exhaustively resolved.
Toad and original Physical05 helpers/footage are unchanged.

## Changed-path verification

One serial source batch executed the two new real run_async Apps, all six existing
viewport target/capture cases, scoped capture/offsets and caption damage. Nine
cases passed in the original batch. The Undo case's offscreen keyboard assertion
failed because original Hide handling blurred the editor; the original log is
retained as offscreen-key-refusal.log. No production code changed after this
result. The corrected case invokes the retained editor's original Undo action,
executing the real selection watcher and scroll-region reader: **1 passed in
0.77s**, undo-path.log. The other nine cases were not repeated.

The Undo App verifies only viewport/retained-path arrangements during the changed
action, unchanged original full-map identity, preservation of a prior offscreen
reader, and exact agreement with the explicit complete-map coordinates. The other
new App verifies completeness invalidation cannot reject committed coordinates,
and actual removal still revokes them. Existing cases cover cached body/overlay
geometry, explicit reader paths, foreign/removed targets, scoped capture's missing
child refusal and damage retention. Complete enumeration remains explicit.

After: 249 production modules, 465 tests and the same 288 Toad dependency modules,
zero parse omissions. One published scene owns existing coordinate selection;
position/membership no longer independently demand complete enumeration.

This qualifies native source reader behavior through HeadlessDriver Apps, not a
latency result or matching Toad/terminal acceptance. Original mutation, inline,
translucent and hit mechanisms were not changed; those full workflows are not
newly qualified by this gate. No Physical05 repeat, installed package, native
artifact, saved source, provider or public runtime operation occurred. Both new
Apps returned through original shutdown; no operation remains running.
