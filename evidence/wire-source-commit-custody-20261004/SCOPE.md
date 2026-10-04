# Wire row commit and receipt resource custody

Source checkpoint with original failed installed attempt. The base is merged #432, `fb0447639cdba02aee0342170600783d66dab6eb`.
Its accepted installed 15.539s result remains historical qualification of that source;
it does not qualify these new bytes. The separate installed01 attempt below does not qualify unfinished cases.

## Source ownership

- `MountedMessageHistory.insert_page` acquires new native rows under the existing
  `AsyncExitStack`. The existing `HistorySourceSnapshot` now covers the mount await,
  including generation, original window/screen and reader request identity. A declined
  acquisition retires only its uncommitted rows.
- Committed association, style, original replacement-read bounds and retained-window
  trimming precede receipt registration and native retirement. The borrowed
  `HistoryReadResult` supplies replacement policy; no copied policy field is retained.
- Original native `AwaitRemove.prune` synchronously retires the scene and already
  owns an independent teardown completion/error delivery. Wire page admission no
  longer joins an unrelated old row's `Unmount` while holding `history_lock`.
  Acquisition cleanup still joins uncommitted resources. Reader acceptance still
  follows the original native reader-compensation context; it is not writer proof.
- `ConversationKind.remember_page` borrows one committed view-key cohort for all
  receipt relations. Channel/DM leaves use their existing `current_identity` owner
  to admit authenticated backend pages. Synthetic style/send row pages preserve
  preceding receipt resources instead of replacing them with unauthenticated pages.
- Style-only replacement borrows the original mounted message cohort directly;
  it supplies no backend `MessagePage`. Combined archived/live rows can have equal
  sequences, while a genuine backend page requires ascending unique sequences
  within its source. That competing synthetic page construction is deleted.
  Absence of a new page is an operation input, not a retained flag or receipt copy.
- Historical/channel pruning moved from paint observation and pre-acquisition tail
  replacement to row commit. DM tail authority survives only while its original
  newest row is committed. No frontend read ledger or second receipt store is added.
- Painted acknowledgement still uses `AcknowledgementViewport`, original backend
  display basis/scope and `run_selected_write`. Selection captures the existing
  source snapshot before queuing work; a stale failed acknowledgement cannot reset
  a successor source. Historical failure retires only that original page's entries.

## Related consumers

The single `insert_page` caller, both changed/no-op `remember_page` branches, all
`remember_tail`/`remember_mounted` declarations and dispatch calls, the single
`mark_page` worker admission and both receipt readers are migrated. Initial/reset/
close receipt clearing and successful identity-conditional acknowledgement removal
remain genuine original resource retirement. No native source or timer is changed.

`owner-before.json` uses existing refactor-audit `Package.load` over all 288 Toad
production, 394 test and 249 frozen native modules, with zero parse omissions.
The broad named-site census includes unrelated `current`/`accept`/`restart` sites;
AST names do not prove dynamic dispatch, external aliases or callbacks.

## Remaining acceptance

The existing `message_dividers_pilot.py --row-publication` control is migrated. Its old waiting-worker assertions were an old completion contract:
it now awaits the same admitted native source worker before releasing the original
pending `Unmount`. It also exercises a real registered replacement read and an
actual native row `Mount` suspended across original source park/cancellation.
The same private App attaches an original archived wire with overlapping message
sequences and restyles the complete actual history through the original controller.
No mounted-event answer, backend actor, display or teardown result is substituted.

Close this affected App control once after coherent source: interrupted
native acquisition preserving committed rows/receipts/bounds; page source progress
and authenticated receipt continuity while old `Unmount` remains pending; replacement
trim bounds; actual visible acknowledgement and stale acknowledgement rejection;
editor/resize/park/whole-close. A fresh named holder purpose is required before an
installed run. No accepted #432 rerun or holder access is implied by this checkpoint.

Earlier production checkpoint `f9270c4f0fde2de5f49db5bcbf9590711f966174` has exact automatic
Debt ratchet SUCCESS, run `37213588265`, job `111469503458`. Changed-file syntax and
diff whitespace pass. `owner-after.json` closes the same full production/test/native
source census with zero omissions. Source evidence does not qualify an installed App.
The subsequent synthetic-page deletion changes production; the earlier green run
is not its qualification. Final production/control checkpoint
`96c8b1f3e0bc27fe1a996e88d10b525dbb7b26cf` passed exact automatic Debt run
`37214994957`, job `111473585764`. Original source admission precedes snapshot
acquisition, preserving detached/retired refusal before accessing native resources.
The source census is bound to this final production; control bytes are unchanged
from `e56cbe8825628ca916664529313657eb554a8d60`. An evidence-only successor does not
change that source qualification. The original installed01 failure below is retained; the corrected control is unrun.

## Original installed01 failure and successor oracle

The one granted original App exited 1 after 16.594132s at the frozen-cohort assertion
following `pilot.pause()`. The exact differing keys were not exported. The source
permits `_check_edges` to admit older canonical rows during that pause; this explains
why the oracle must allow admitted source growth, not what the failed tuple contained.
No final App receipt was produced. Pending Mount cancellation, archived/live overlap
and final whole-App assertions remained unreached. Sequential receipt/source progress,
replacement bounds, resize and editor checks before the assertion are documented
without relabeling the failed run as a partial PASS.

The changed oracle retains every admitted replacement key and requires actual rows
to equal the original canonical page filtered to actual keys, in original order.
It rejects foreign, duplicated, lost or reordered rows while allowing original older
page admission. Only this control changes; production remains byte-equal to `96c8`.
Parent authorized one successor affected App after a fresh specific Bohr purpose.
No accepted #432 repeat, product patch, movie, provider or public quiet window is needed.

The actual436 floor was restored: all1470 archive members,69 package versions and390
protected keepers exact, original origins/activation preserved. Own final253 allUID
census recorded zero references/gaps; Bohr independently closed the purpose with a
separate246-process census. The issued grant remains immutable; only Bohr owns its
lifecycle close. `installed01/keepers.json` binds the original failure, source proof,
issued grant and whole-floor handback. The successor must restore that same floor.

Full scrolling/runway/sidebar/thread-open performance remains active. No CPU dominance,
measured speed improvement, smoothness or FPS is claimed.
