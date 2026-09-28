# T5 destination and row caller closure

Worktree: /home/ts/wt/toad-t5-sol-20260928. Existing PR121 branch reused.

One NavigationTarget declaration family now owns each row destination's activation, menu capability, unread projection and channel expansion behavior. CommsRow is a Textual presentation of that owner, not a second semantic kind registry. ChannelLike shares channel behavior across channel/feed members. ThreadRow retains the real open-view identity; relationships revalidate the current source before using its nominal destination. Virtual choices dispatch their own activation/menu/toggle behavior, including NewSessionChoice with no fabricated destination fields.

Deleted NavigationTarget.decode/from_name, both hand-maintained target dispatch dictionaries, row/choice kind fields and comparisons, _person_kind string projection, SelectTarget's kind payload, and two view navigation forwarders. Every production message/row/navigation caller and every current test caller now supplies a nominal destination. Removed the old mocked decoder/type-dispatch test block and raw row-kind assertions. Link identity classification occurs once at the existing link boundary. Core RelationshipEntry source keys remain untouched; this PR does not duplicate their store/schema. No persisted format changes.

Changed production paths: navigation_target.py, app.py, screens/{main,comms,pending_thread,goal_details}.py, widgets/{comms_sidebar,thread_comms,virtual_channel_list,irc_message,route_header,channel_participants,goal_text}.py. Tests migrate the existing API callers; test_sidebar_destinations adds a mounted new-case test and retirement guards. Source diff for this batch: 201 added / 165 deleted. Existing test diffs: 178 added / 122 deleted, plus 58 new family/guard test lines. Net additions are the nominal virtual-choice declarations and direct typed constructor imports replacing string decode call sites.

Fresh installed-wheel receipts (no source PYTHONPATH override):
- navigation-owner.txt: actual two-owner navigation, Back, reuse, stale owner and close isolation pass.
- navigation-shared.txt: one retained shared Channels tree/rows/tasks across destination frames pass.
- navigation-relationships.txt: mounted right sidebar five-group/navigation/sort/collapse fixture passes (supplementary fixture evidence).
- navigation-virtual-final.txt: virtual roster two-owner navigation passes.
- navigation-links.txt: clickable routed spans and keyboard navigation pass.
- navigation-final-new-case.txt: mounted one-class new destination and deletion guards pass (2 tests).
- navigation-native-current.txt: installed Toad -> ACP -> actual owner -> native Pi path passed queued input ID/consumption, cold reattach, DM reply, channel active/idle/Checked, stopped owner reopen and idle interval. Loopback-only model fixture, no paid calls. Idle2.11s: owner0.11CPU seconds/UI0.67/no model requests; this short check is not a global performance claim.

The first native test attempt (navigation-native.txt) refused the entry-store0d package because this core pins native689; its failure is preserved. The successful native test uses native-current-689ce4b5d0592b9a. The candidate then pinned Comms1853503b432144e9a3becf358bb870b6b71c8119, matching the now-live core, and freshly passed mounted destination guards/new case and actual native-bound goal-owner test (navigation-final-server.txt). After deleting the two extra view forwarders, navigation-owner-final.txt rechecks owner navigation on that final wheel. Build/install receipts identify the owned environment. Textual16ede is unchanged. No live roots/routes/launchers modified, converters or ratchet script restored, input replay, CI wait or paid calls.

Shared contracts: CONTRACTS.md specifies the minimal T6 replacement of existing HistoryKind. This batch keeps that owner until Noether's family checkpoint; it introduces no duplicate ConversationKind. Dalton T2 owns ACP record/failure declarations; Tesla T3 owns thread command declarations. Existing116 retains workspace lifetime ownership. Remaining T5: RowAction/thread-command menu consumption, transcript lifecycle/filter/event merge, T2 delivery failures and final T6 kind consumption, sidebar class queries. None is marked done by these receipts.
