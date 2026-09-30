# Canonical ACP launch admission

Owner: Schrodinger. Parent owns installed dead-owner UI verification and activation.

Live reproducer: opening refactor-r1 after the lifecycle cutover starts an ACP
child with AGENT_COMMS_ROOT but without the selected private root/package pins.
An already-running owner attaches; ensuring a dead owner fails strict launch.

AgentProcess.start prematurely pins the root. admitted_spawn then mistakes the
mutated environment for an explicit override. Preserve original environment and
carry the existing RouteSelection witness into spawn and prompt admission. Only
locked spawn admission publishes the root and private pins into its child copy.
Delete the separate process root/implicit fields and migrate their consumers.

Patterns: IDEN-1 selection origin changed by its own projection; BOUND-2 route
owner bypass; IMPL-13 competing launch admission interpretations.

Acceptance: actual installed implicit default -> dead registration -> ACP load
-> strict private native owner launch -> ready saved source, without prompts or
replaying failed input. Preserve explicit independent roots, conflicting pins
denial, stale default-route denial and cancellation/child custody. Parent owns
the continuous baseline/candidate UI gate. This draft is not ready or live.
