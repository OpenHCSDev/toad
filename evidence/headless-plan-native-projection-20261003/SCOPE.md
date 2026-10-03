# Headless plan facts, original native projection

The original PlanStatus owns ACP status admission and completion facts. It also constructs Textual Content, Plan widgets and StrikeText resources. Core Plan events and AgentController import that data family; an operational plan must not require native widget construction.

Keep the same PlanStatus/PlanItem declarations and original external ACP names. Markers become plain text. Original Plan owns native composition and previous-status animation intent; original StrikeText owns completion decoration and its refresh/animation lifetime. Delete PlanStatus native compose/decorate methods and migrate every marker/content caller, including existing extension and registered SDK/App fixtures. No new type, registry, copied plan source, compatibility path or generic frontend.

Source semantics and existing NRA AST across production/tests precede implementation. Patterns IMPL-13 and BOUND-2. Existing controller retains admitted entries; widgets borrow their exact source values. This checkpoint does not change controller delivery, sidebar publication, viewport or lifecycle ownership. Heisenberg was contacted directly before native methods change. Native plans and streams are distinct: OutputStream still has its own unfinished frontend lifetime and is not folded into this checkpoint.

Same existing checkout and dependencies; no new WT/env/native/provider. Publish coherent source before checks. At the end use one batched sanity plus the existing installed original App/ACP plan journey for actual marker paint, pending-to-completed animation, reset, detached update and reattach. This detects missing native completion invalidation and loss of original plan source on retirement. No repeated permission/shell/cold ContextTree gate. CI deferred; no full headless/performance claim.

## Published source closure

Working production checkpoint873b981f; completed journey receipt support1fe944dc. Three production files24 lines added/45 deleted. No native import or compose/decorate operation remains in PlanStatus. All PlanItem constructors use original string content; markers have one plain-string contract, including the existing declaration-extension fixture. Official ACP admission and FieldCodec PlanItem shape remain unchanged.

The source chain is SDK AgentPlanUpdate → SessionUpdateEffect.plan → decode_plan → AgentController.publish_plan → CoreEventStream Plan → Conversation and MainScreen native recipients → existing Plan → StrikeText. Original controller owns latest admitted entries. Native widgets borrow the same list; previous_statuses remains bounded historical paint intent for completion animation, not ACP admission or plan authority. No new source copy, status registry or frontend family.

Existing NRA AST parsed289 production/392 tests with zero omissions before/after. Dynamic receiver binding remains a semantic/runtime obligation. Textual MessagePump.call_after_refresh queues InvokeLater on the original widget; after mount its original pump forwards to Screen refresh completion. StrikeText therefore owns the animation scheduling resource itself, replacing the former parent callback. Final installed ACP/App fixture must verify this changed scheduling and marker paint; source parsing does not certify it.

Actual installed validation remains pending a named released existing holder. Parent confirmed485 is futurecurrent and334 rollback; old metadata directories are not environments. Heisenberg's style22 sequential loan is requested through its owner. No holder is modified without release, no new environment is created, and397 publication is independent. This is a published source checkpoint, not Ready/live acceptance.
