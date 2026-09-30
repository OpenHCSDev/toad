# C0/T4: native widget action availability and dispatch

Receiving owner: Mendel. Original row: cleanup-2026-09-29.zip C0-enforce-polymorphism.md Conversation/Question::check_action; parent14 C0 ledger keeps it open. Audited Toad main645d63d1c885ef26f056e34a7c61530c90ce331b. Patterns IMPL-5/7, MEMB-1/4, BOUND-1.

## Census and ownership

Conversation.check_action compares five native action names: terminal focus, modes, cancel, expand and collapse. Question compares selection-up/down/select-kind. PermissionsScreen copies select-kind option/parameter classification instead of querying Question. Native Textual650 checks dynamic availability before dispatching action_<name>, including footer state: True enabled, False hidden, None grayed. The namespace and action syntax are external contracts; that does not excuse keeping our cases as switches.

Heisenberg227 grants methods-only scope: Conversation.check_action and action_focus_terminal/expand_block/collapse_block/cancel/mode_switcher. Mount/layout/history/focus integration remains227. Question availability/action methods and PermissionsScreen forwarding are this receiving scope. Sch229 publication/header methods disjoint. Parent owns canonical turn/input/cancel semantic contract; retain public turn.owner.busy and original cancellation worker/two-Escape behavior. No private active-turn probes or state copies.

Existing ApplicationAction parse/apply, KeyboundAction and shared DeclaredFamily are the available owners. Extend the native action contract so action declarations own parameters, availability and effects; generate native namespace/bindings from declarations, not a second command inventory. ThreadAction/TargetContext continue to own durable Comms command permissions, not these widget navigation/choice effects.

## Required closure

Delete both named check_action switches, the copied PermissionsScreen availability logic, and replaced dynamic action methods/callers. Keep one authoritative Question option selection and original Ask callback identity. Native Textual actions not belonging to this widget family retain framework handling. New-case experiment must add a declaration without editing dispatch/availability catalogs. Extend existing T4 guard against action-name dispatch, backed by real historical sites.

Verify installed saved-state Toad with actual native widgets and physical click/key input: retained history block cursor expansion/collapse, question selection and disabled actions, permissions forwarding, draft return. No provider calls, replay, live mutation, desktop display or canonical lifecycle substitution. Evidence distinguishes source/native widget behavior from paid-provider acceptance. This draft is not ready until deletion, bounded ratchet and affected installed journey pass.
