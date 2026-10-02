# Pure-channel handling and response feedback: read-only consumer review

Installed frozen cohort remains Core5c74f0ec/Toad7df5e61c/Text68a0d1cf. No production changes, prefix mutation, public input/replay, additional process/provider/test or new authority in this review.

## Required relation

A saved assistant answer is not proof that the current original channel message was handled or answered. Use the exact original MessageReference, frozen recipient identity, canonical WakeAssignment, its execution and original per-route PublicationReceipts. Sequence326 and an older PR159 reply must not be conflated.

## Producer and settlement

- SelectedTriage.parse decodes the original bounded model result once with the existing FieldCodec/declared family. DecidedTriageOutcome sends that original decision to TriageNativeSend.commit; native proof and original claims settle together. Rejected results use the existing failure outcome, never an invented success.
- IgnoreSelectedTriage settles the captured originals to IgnoredAssignment in the same proof transaction. That lifecycle owns `Checked — no response` and its explanatory text. FullSelectedTriage's existing continuation owns execution creation from the exact proved originals; no receiving-side decision switch.
- A FULL execution retains every original source and route obligation. coordination_response publishes each original route, records keyed PublicationReceipts, and publishes the corresponding PublishedResponse. RecoverySnapshot.finish_publications marks claims Completed only once EVERY required original route is published. A raw native assistant entry alone does not perform that settlement.
- ResponseConversation captures the obligation's exact original assignments/deliveries and freezes their audience. Channel replies include the original conversation audience and executable original senders; unrelated direct answers retain their separate route.

## Canonical presentation and consumers

- NotificationAssignment.for_delivery matches both the original MessageReference and frozen recipient lookup; duplicate matching receipts are rejected. Its read-only original lifecycle projection supplies Pending/Responding/Paused/CheckedNoResponse/Responded, rather than guessing from saved answer prose.
- MessageNotification.delivery_window reads the original assignments, frozen audience and current recipient observation, keyed by `(seq,message_id)`. Recent incoming feedback retains the actual original message alongside its handling result. The existing live-turn timestamp predicate checks that a declared turn began before the assignment update; no new interpretation was introduced.
- Core history_views.message_notifications and message_notifications_for_references share that projection. Missing current handling remains missing/unrecorded; errors remain visible. HistoricalMessage's own source authority prevents an archived body from silently acquiring today's same-name live handling.
- IRCMessage and compact IRC rows mount MessageNotifications on each actual wire message. CommsChat reads the bounded painted message window via Core's message_notifications and applies only the same `(seq,message_id)` result after current route/tab/resource checks. This refresh is independent of bus-message append revision, so SQL handling settlement need not append a synthetic message.
- IncomingMessage and OutgoingMessage share WireMessageHandling. Their message_reference is the original transcript event source. HandlingPublication reads those exact references through the existing ACP Agent/controller transcript reader and updates still-attached bodies only under the captured publication owner.
- Mounted DM bodies request handling. CoordinationChangedUpdate refreshes the existing ObservedThreadActivity; its current presentation requests ObservedSourcePublication. An accepted source publication also invalidates message handling; no duplicated status authority is authored here.
- ObservedThreadActivity renders the original incoming target/sender/body excerpt plus its canonical handling state. It does not establish receipt from an earlier assistant answer. Session-details/recent summaries and message-level feedback remain views of the original Core source.
- HistoricalSessions.publish_handling validates the selected archived source and uses its original references/provenance rather than decoding or scheduling a current live owner.

## Finding and boundary

No new concrete receiving defect was established by this source review. Current-original handling is already exposed in the corresponding channel row and inbound/outbound DM body, with per-recipient details; saved assistant text must not be used as the acceptance oracle. Original326 native/disposition evidence is owned by parent/Arendt; this review does not assert that326 was answered or reinterpret its recorded IGNORE.

Singer owns the NEW configured manyowner PURECHANNEL journey using the frozen final prefix. Parent accepted the existing exact-source-equal performance03 proof, not a newly recorded run. Package/source checks are complete; whole affected release readiness waits Singer's final actual receipt. Parent alone activates defaults.
