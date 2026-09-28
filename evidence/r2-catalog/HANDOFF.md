# R2 paired Toad catalog consumers

Core192 merged at054028b5c7cc3a36c964d1abbfd78af60c13545e.
Two production callers migrate directly to catalog.read().resolve: navigation preparation and sidebar menu. Current views/sort/any-mode pilots use the same document API; no compatibility methods restored.
The broad channel pilot also used the removed two-argument finish_turn; it now retains actual begin_turn leases and uses test-owned RuntimeServer teardown.

Local source acceptance against current core192:
- Any-mode mounted menu/history/unread passed.
- Session sorting all criteria, stable selection and shared settings passed.
- Full channel views passed: union membership, tag updates, persistent tabs/drafts, navigation, channel/member pins in both views.
Earlier failures retained: removed resolve API; removed finish_turn API; one pinned-row assertion on the broader pilot. The latter attempt timed out during teardown and is not green. The completed diagnostic run uses proper test-owner teardown and retains row-state diagnostics; no production pin-order defect was established.

Installed paired wheels in runtime-r2-catalog-20260928:
- Mounted any-mode menu/history/unread passed.
- Parent actual historical UI mounted original #comms/#nra and111 saved-session choices plus original transcript; live sequence unchanged.
- Parent compared8478 stored/live Message projections and all catalog projections across3 copied roots with zero decode failures and exact equality; one-way migration/reopen preserved document values. Owned copies removed after the compact receipt was retained.

Source pilots use bounded60s commands; completed broad pilot allowed165s after the earlier failure/teardown timeout. Installed history and any-mode use60s. No provider calls, CI waits or old input replay. Parent owns live activation.
