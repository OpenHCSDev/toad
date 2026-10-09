## Receiver-side inbound visibility

The collapsed agent tab previously said only `5 recent`, even when an agent had handled channel messages in a separate selected native session. Show the latest assigned message's channel/sender/decision in that always-visible row. The existing expanded details retains the message excerpt and the channel view retains complete history.

The maintained one-owner App/native/ACP/wire journey checks the receiving agent tab during a real selected turn. It asserts the inbound source appears in the rendered tab and the original body appears in the expanded activity view.

## Evidence and remaining acceptance

Actual installed App/Pilot read-only probe against the live NRA exchange showed `#nra` seq174 as an `Inbound` row in the receiver's channel view, while its native tab summary said only `5 recent`; old messages fall out of the five-row native summary. The same physical pilot with this source branch painted `Latest inbound #nra ...` with no prompt and no bus mutation.

The new maintained journey passed using this branch's noneditable Toad wheel over the installed core and canonical native package. It sent through the real channel composer, received the message in one actual selected Pi process with a controlled localhost provider, returned to the recipient tab during that turn, painted `Latest inbound #team`, and found the original body in expanded activity. No replay or live bus mutation. The same source journey passed before wheel packaging.

This improves discovery of the latest inbound assignment; it does not yet provide a durable unread ledger or a complete native-tab inbox for every older assigned message. It has not been activated in the user's Toad launcher. Resource headroom warns, so the larger multi-owner journey was not repeated just to exercise this one change.
