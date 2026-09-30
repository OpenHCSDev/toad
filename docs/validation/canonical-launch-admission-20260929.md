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
the continuous baseline/candidate UI gate.

## Source checkpoint

Production checkpoint `7b86e838`: 27 production lines deleted, 34 added. Deleted
the independent `AgentProcess.root` and `implicit_root` fields, premature root
projection, and spawn's repeated environment-origin decision. `RouteSelection`
captures the original child selection once; spawn consumes that witness under
the existing route/admission locks and only then projects root/package pins.
An active route changing its package or root identity also rejects the captured
selection. Explicit independent child overrides retain their admission rules.

Provider-free `default_route_prompt_selection_pilot.py` passed through actual
Agent.start and an actual subprocess. Original implicit environment stays
unmodified; a stale default prompt is denied and an explicit child remains
independent. Migrated its deleted dict AgentDefinition and both implicit-root
field consumers to the current owners; no compatibility aliases.

Required `agent-comms-ratchet --root src/toad --base 3b019 --head 7b86e838`
passed with no positive debt changes (StringSubscript -1).

`default_route_admission_pilot.py` did not complete: after migrating its two
deleted `_wire` consumers to `message_history.service`, its existing StartAction
spy timed out before reaching spawn admission. This is not a passing gate and
does not establish a launch regression. Parent's actual installed default-route
dead-owner UI journey is the outstanding readiness boundary. No user inputs,
live owner restarts or global package changes were made by this worker.

## Installed acceptance: READY

Parent executed the actual installed `toad-comms refactor-r1` against the
original live failing registration with Toad `7b86e838`, Core `720629`, Textual
`412b` and native `4ab`. The existing dead registration ensured a new real owner;
its root, root ID and native package match the authoritative active route.
`session/load` succeeded with 40 saved events, zero errors and zero prompt
requests. The parent closed only its test window; the user's window was untouched.
Receipt: [candidate-dead-owner-launch.json](../../evidence/canonical-launch-admission/candidate-dead-owner-launch.json).

Normal integration of merged viewport #214 (`cc68c51e`) changed none of the
three launch production files from tested `7b86e838`. This checkpoint is ready
for parent merge/activation. The default install has not been changed by this
worker; activation remains owned by the parent.
