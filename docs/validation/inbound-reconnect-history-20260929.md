# Inbound history after observation, pruning and reconnect

22 production lines deleted. The mounted-widget-only projection moved from `Conversation` to the existing source-fenced `TranscriptPublication` family. Automatic native-conversation pruning now uses the existing committed checkpoint; it cannot delete source history or uncovered wire identities merely because their rows exceed a display budget. Explicit window clearing and offline terminal pruning retain their existing meanings.

Owner: this branch, Toad PR204. Tested candidate production revision: `7fc674cf4ceceb733d30ced51d3d633283e11a8f`, paired with Core `707c91170fa307f7ec75199baea00d7e55c47dab`, Textual `412b5a2b5da8875dc2f3dc5be2365abddce0537b`, native package `native-current-776dc36857e630da`. Latest main including PR199 is integrated.

## Cause and ownership

- IDEN-6 / BOUND-2: DOM presence answered whether a wire record already had a presentation. Committed source coverage was bypassed whenever its body was unmounted.
- The independent row-count pruner also removed `TranscriptHistory` and `SequenceClaim` widgets without committed evidence. A later observation could therefore append an already displayed receipt again.
- `AssignedInboundPublication` inherits source, agent, widget and generation fencing. It consults `CommittedHistory.source_coverage` and updates every mounted counterpart's handling in place. No seen-ID collection, additional store, timestamp cutoff or provider retry is introduced.
- Lazy native incoming bodies read handling from the existing `ObservedThreadActivity` source. Coverage publication retries any receipt deferred while its source was provisional or parked.
- PR202's owner confirmed that a validated parked-source reveal emits `Covered`, including an unchanged native cursor. The source-coverage edit is disjoint from that owner's retained-history and End-navigation changes.

## Installed continuous acceptance

`tests/inbound_history_reprojection_installed_pilot.py` runs the real installed Toad UI, actual ACP process, detached owner, selected native Pi and private wire, with a controlled localhost provider. It sends a real agent channel message, performs a native user turn, physically scrolls the continuously open recipient, delivers another channel message under actual row pressure, reconnects ACP, physically clicks the channel bar and returns via the recipient tab.

- Installed current baseline PR199/Core409 failed the old inbound's retained identity after physical PageUp, measured 110 rows above the configured 100-row pressure threshold, and a fresh channel assignment/activity publication.
- Installed candidate exited 0: the original inbound object survived the same pressure and late handling update; the fresh identity appeared once. Reconnect and channel/tab return did not make provider calls. The returned old message retained its original recorded clock.
- Exactly three localhost provider requests were made for three explicit fixture inputs. No real provider calls, user-bus changes, active-user-owner restarts or uncertain input replays occurred.
- Latest NRA census: no added string dispatch, type switches, long boolean chains, codec subclasses, attribute-by-name accesses or broad exception handlers. Optional probes added here concern genuinely optional notifications, loaders and framework observation widgets; no optional state fields were added.

The receipts are in `evidence/inbound-history-reprojection/`. This is verified in the isolated installed candidate. The default live installation still requires the integration owner's activation.

## Remaining scope

Large-source lookup cost and the paired PR202 retained-source reveal are not performance-certified by this small fixture. Source coverage uses bounded existing page reads, not a second index or record cache. Exhaustive older assignment history and chronological interleaving for channel work that has no native transcript counterpart remain part of the broader history/refactor work; they do not hold this demonstrated replay fix.
