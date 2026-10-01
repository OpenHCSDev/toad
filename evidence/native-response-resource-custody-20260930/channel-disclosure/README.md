# Shared member preparation and disclosure custody

Original u04: #team physically expanded but empty for 20 seconds. Post-failure
canonical source has beta in #team; its timing does not prove the failure-time
snapshot or preparation state. Preserve that installed failure without replay.

The source reproducer uses actual ToadApp/ChannelGroup, original private canonical
membership, real worker-prepared ThreadRowsWork and native compositor strips.
Only the delivery of completed preparation is held to expose the crossing.
Frozen source dependencies: Core ba938, Textual 2e49, SDK 0.12.1. No native owner,
ACP process, provider, input or public root mutation.

Baseline: update_members installs a newer source before acquiring its member
lock. The disclosure already preparing beta then rejects its original snapshot
by object identity and completes with zero rows. Another update owns the lock
next but still awaits preparation. Snapshot/model installation and rendering
were two different lifetime transactions. RelationshipRows.update_group has
the same source-installation-before-lock procedure (IMPL-12).

SidebarGroup now owns the existing member lock and serialized disclosure
reconciliation. Both concrete source update methods install their original
model and await reconciliation inside that same lock. Two subclass lock
definitions and wrappers are deleted. No extra callback, timer, loading state,
semantic store, generation flag, format alternative or compatibility entrypoint.
New group cases inherit this resource custody instead of inventing another lock.

Disclosure remains the existing authority for expansion. Channel commit derives
its final member keys from current expansion after preparation. Relationship
visibility likewise commits its collapse/reveal branch after preparation, keeping
the original bounded rows and scroll custody. No captured expansion flag/retry.

Candidate actual application checks:

- beta is published while a newer original metadata preparation remains held;
- native collapse/expand clicks pass and beta is in actual compositor strips;
- an actual collapse click during held preparation commits two empty keysets,
  never expanded rows, then reversal reveals beta;
- actual canonical beta-parent/child relationship rows survive an unchanged
  source update and collapse/reveal with original resource identity;
- normal application shutdown, no caught/suppressed product exceptions.

The first held-click driver blocked its second click behind Pilot's all-pump
readiness barrier. It is retained as driver-control failure, not a product
verdict. Corrected source reconciliation runs outside the widget message pump
as production observation does; a real click remains deliverable. A subsequent
driver inspected a newly mounted relationship group before its rows completed;
that failure is retained too. Final readiness waits for original rows to mount,
then checks exact identity and content without changing product behavior.

`candidate.json` and `candidate.log` are the final source result. `ratchets.json`
contains bounded per-file screening: no string/type dispatch or arms, codec
subclass, foreign absence or six-term chain debt added. Guards seal inherited
member locking and original source installation inside it. No global TC1/T9 or
full native/physical readiness claim. Installed u04 closure remains the next
single corrected joint cohort journey owned by Einstein; this proof does not
establish that u04 reached this precise race.

```sh
CHANNEL_DISCLOSURE_ARTIFACTS="$PWD/.artifacts/channel-disclosure-complete" \
PYTHONPATH="$PWD/src" timeout 25s \
/home/ts/wt/toad-foreground-readiness-sidebar-followup-20260930/.artifacts/installed-body-readiness-253/bin/python \
tests/channel_disclosure_publication_pilot.py
```
