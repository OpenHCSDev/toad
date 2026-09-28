# T6 declaration consumption in T5

Noether's published85a63d557051138980dcb504137a81e80990c359 imported as44fdfa7. Conflicts in navigation_target.py and async_tab_activation_pilot.py retain T5's typed destinations and deleted decoder/mock type-switch block. No old dispatch dictionary, from_name alias or HistoryKind restored. New ConversationKind family is consumed directly; its current/history read basis and bounded page behavior come from Noether's owner, not a second T5 implementation.

Fresh installed wheel on Comms1853503b432144e9a3becf358bb870b6b71c8119/Textual16ede/native689:
- kind-integrated-family.txt: new declaration and actual read family test pass.
- kind-integrated-history.txt: four tests pass: archive attach/detach, scope expansion, DM turn lease identity and bounded/cancelled read ownership.
- kind-integrated-navigation.txt: mounted two-owner navigation/reuse/Back/close isolation pass.
- kind-lifecycle-native.txt: complete actual ACP/owner/native path passes queue/native ID consumption, cold reattach, DM response, channel active/idle/Checked and stopped-owner reopening. Loopback fixture only, no paid calls. Idle2.03s: owner0.07CPU seconds, UI0.59, no model requests. No global performance claim.

T3 and T6 coordination posted once on their existing PR120/123 threads; comments are durable contracts, not proof that either worker has read them. T3 target_commands.py currently already owns Copy/Close/Pin, so T5 will consume its published coherent checkpoint rather than invent duplicate RowAction classes. It still uses a boolean context discriminator; the coordination request names this new-code issue and asks T3 for nominal context members/destination capability.

Next independent T5 batch: filter overlay state/source component and event-owned merging. No current blocker on those. Full surface remains draft until these and menu/failure/class-query callers close. Live installation untouched; parent owns final deployment. Owned generated native fixture dumps/build copies are removed after retaining these receipts.
