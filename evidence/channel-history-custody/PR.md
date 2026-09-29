# Mounted channel/DM history ownership

CommsChat's mounted row window, paging locks/edge work, canonical read request/publication, style replacement and exact paint receipts move into MountedMessageHistory. The actual state and effects migrate together; no root forwarding API or second cache/reader/preparation mechanism. ConversationKind's existing channel/DM declarations consume that explicit owner and remember receipts only at committed page publication. Existing ChannelHistoryReader and source identity remain authoritative.

IRC/Markdown style behavior lives on declared WireMessageStyle cases; boolean style dispatch is deleted. CommsChat owns membership-notice/direction rendering and operational send/notifications, with no duplicated row-window/ACK state. Screens and maintained test callers migrate in place. Tesla native source/cache/TranscriptHistory and Noether App/Prompt remain disjoint.

CommsChat732→388; mounted owner382, no class crosses500. Touched-file foreign-absence/chain/excess500 ratchets pass. IDEN-1/3, IMPL-4/5/8, MEMB-1 and TIME-3/9 apply. Draft remains unverified: actual installed displayed-only partial-paint and continuous saved-state native journey are the acceptance gates. CI deferred; no live mutations or paid provider calls. Parent owns merge/install.
