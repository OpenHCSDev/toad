# T5 crossings

The current kind owner is `channel_preparation.HistoryKind`: CHANNEL (`channel`), DIRECT (`dm`), ALL (`irc`). Navigation's HistoryTarget subclasses already own which kind to use. T5 will remove all row/choice/name-kind decoding and pass nominal NavigationTarget instances directly. It will continue consuming the existing HistoryKind until T6 replaces that owner; no second kind family is introduced here.

Minimal T6 declaration required: a ConversationKind family with Channel, Direct and All members replacing HistoryKind in place, and each member owning `page(comms, target, project, after, limit, max_bytes)` plus `display_identity(page)`. HistoryTarget's existing `history_kind` declaration becomes a ConversationKind member. Channel/All share page and channel display-basis behavior; Direct owns dm page and direct inclusion basis. The family owns external spelling only at any actual serialization boundary. Session/thread navigation are not conversation kinds. T6 may choose constructor names; T5 needs these two methods, not a separate codec, registry or bool capability roster.

T2 Dalton owns GoalChanged and DeliveryFailure boundary records. GoalDisplay currently consumes the existing paired owner snapshot; T5 will adopt the decoded T2 record once its consumer contract lands. T3 Tesla owns ThreadAction; T5 consumes that declaration for thread menus and does not create a competing action-name catalog.

PR116 owns workspace/session lifetimes. No alternate workspace is introduced. T5 changes only destination/navigation ownership and row presentation of that destination; shared chrome, mounting and inactive view retirement remain PR116/T4.
