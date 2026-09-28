# Implementation dispatch — 2026-09-28

Source: owner's `plans/toad-comms_refactor/toad-refactor.zip`, preserved verbatim
in this directory. Current starting fork heads: Toad43e57c9, Textual16ede00;
Comms242 is merged and installed. Re-read each surface against its dispatch head.
The older audit heads in the supplied documents are evidence, not a reset target.

## Standing owner overrides

- CI remains asynchronous and is not a merge gate. Implement the shared ratchet,
  collector, workflows and local guards required by TR0; local tests plus actual
  affected installed paths govern shipping. Do not enable required CI rules from
  TD2 while this standing owner instruction applies. Keep the source plan intact.
- Complete current Comms refactor/deletion/native-capacity tasks first. New Toad
  work is additional scope; do not silently abandon an existing assignment.
- Same configured model; persistent worktrees only `~/wt`. No live checkout edits,
  shared-worktree edits, data resets, input replay, or paid provider probes.
- Existing abstractions come from Comms directly; no duplicate family/codec/table
  packages. Every replacement removes all old implementations and current callers.

## Complete-surface ownership and order

Rows name published implementation PRs where available; pending rows remain
assignments only. Native acceptance retains priority while independent Toad work
continues during package prerequisites. Parent assigned TR0 to Pascal after T8.

| Surface | Owner | PR / dependency | Required deletion and real acceptance |
| --- | --- | --- | --- |
| TR0 | Pascal | active; paired draft PRs pending; core ~/wt/comms-tr0-ratchet-20260928 | Move existing ratchet into Comms package and delete script copy; derive pilot collection, remove manual roster and obsolete pilots. Run actual pinned stack locally. |
| TL0 A, then B | Copernicus | pending; preserve current107/109 work, B after T2 | Retire converters/aliases/unused modules, then dual paths; migrate retained data once and remove tools; mounted real-path acceptance. |
| T1 settings | Darwin | active; code-bearing draft pending; native acceptance remains priority | Typed declaration tree and per-kind/effect behavior; delete schema dictionaries, dotted reads and dispatch; load actual saved settings unchanged. |
| T7 terminal | Lovelace | PR114, refactor/t7-terminal-20260928, ~/wt/toad-t7-terminal-20260928; Copernicus integrates107 | Move command/read/mode behavior to owners, delete type/mode dispatch; external escape contracts and real large-stream before/after timing. |
| T8 small boundaries | Pascal | PR115, refactor/t8-small-boundaries-20260928, ~/wt/toad-t8-small-boundaries-20260928; Copernicus integrates107 | Shared terminal environment, typed session/metadata owner, nominal danger behavior; old duplicated launch/schema/caller paths deleted. |
| T2 ACP/Comms boundary | Nietzsche | pending paired PRs, after229 integration and first wave | One declared Comms extension decoded once, all producers and Toad consumers migrated; delete flag/shape probes; real ACP/native/UI route. |
| T6 rendering | Parent | pending; consume110 audit, after first wave | Declaration-owned renderer commands/status/backend/task/kind; remove rosters and enum switches; introduce shared ConversationKind forT5. |
| T3 commands | Darwin | pending, afterT2 | One command family/framework boundary registry; delete command-name switches; mounted commands and actual dispatch. |
| T5 Comms interface | Copernicus | pending, afterT2/T6 | Nominal row/source/navigation owners; delete duplicated literal sets and state representations; channel/DM/history/feedback on real installed path. |
| T4 remaining large classes | Parent | pending, last | Move residual state to real owning components after other surfaces; delete superseded state/forwarding/dispatch; integrated local suite and installed workflow. |

## Existing PRs that must not be duplicated

- Toad107: Copernicus owns paired Comms229 current Goal/queue/process callers;
  shared Channels changes and watcher109 are integrated. Complete this first.
- Toad109/113 are merged and installed via Comms252. Recursive watcher cancellation
  and peer-close behavior passed actual native event tests. Copernicus now combines
  T7/114 and T8/115 into paired107 before taking TL0A.
- Toad110: existing frame-pipeline structural investigation. Its ownership map,
  measurements and invariants inform T6/T4; do not create a competing investigation.
- Toad53: command discovery design is input toT3, not a second command mechanism.
- Toad50: browser serving is a separate feature; its active behavior must be checked
  beforeTL0 removes any code. Do not silently expand the refactor into publishing it.

## Acceptance and reporting

Each code-bearing PR records exact source/test additions and deletions, obsolete
symbols removed, all migrated callers, durable/runtime store classification,
focused and actual installed-path evidence, and remaining named dependencies.
A merged source foundation is not a completed surface. Completion includes the
paired install and deletion of executed one-shot tools. Keep worker artifacts
bounded and clean owned completed copies once receipts are retained.

## Published first-wave acceptance

- T7/114: 44 tests, mounted terminal stream pilot; median5.29s ->5.17s.
- T8/115: focused6 plus mounted PTY/ACP; all46 retained sessions preserved.
- Combined107/current-core installation still pending; individual receipts do not
  claim the whole stack is installed.
