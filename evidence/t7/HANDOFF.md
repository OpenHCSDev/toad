# T7 terminal — implementation draft, acceptance continuing

Lovelace, branch refactor/t7-terminal-20260928, own ~/wt/toad-t7-terminal-20260928 from fork main cc2d35c. User authorized this independent assignment while Darwin assembles243/244; combined native capacity acceptance preempts T7 when the package arrives. Read full T7, 00-RULES, 01-INDEX, 02-DISPATCH and NRA skill. Current open107/110/53/50 do not own ansi/; no competing T7 PR.

## Code and deletion

- Every ANSI command is a frozen slotted dataclass under public ANSICommand ABC and owns async apply (cursor response must await actual stdin). TerminalState retains primitive buffer operations; command match and union alias deleted. Hidden output uses the declaration's visible_output property.
- All reads own feed; PatternRead shares incremental consumption. Parser generator yields reads only and emits parsed results through its existing stream owner. Deleted mixed yielded-type switch, unused cache/debug demonstration, regex buffer/max-length leftovers and EOF projection with no callers.
- Modes consume shared Comms DeclaredFamily directly. Numeric external declarations own mode changes; SetMode replaces optional feature/mouse bags and both hand-maintained enabled/disabled rosters. No aliases or local registry.
- Escape introducers use the same shared family. Terminated strings, designation, invocation and single-character payloads share inherited parsing. Deleted introducer match, DEC slots/invocation rosters and dead debug print helpers.
- External behavior corrections caught while moving the owner: OSC terminators no longer pollute link/path payloads; ESC / designation selects G3; IRM4 enables insertion rather than an ignored flag; disabling mouse encodings restores normal format. Unknown modes have no effect. External escape bytes and ACP/Pi formats are unchanged.

## Stores / cutover / dependencies

Only transient terminal buffers, parser reads, modes and declaration-derived registries. No durable store or format migration. New code depends on parent's round2 Comms DeclaredFamily (TD1); final pair/pin and quiet installation belong to parent. No live changes, providers or additional environment install.

## Current evidence

44 tests pass with actual TerminalState, including whole and byte-fragmented input, external cursor reply, styles/modes/scroll regions, unknown modes, OSC/DCS, new command/mode + collision refusal, read family consumption/exhaustion, AST deletion guard. Exact fork Textual16ede007 source was used with existing Python3.14 runtime and Comms source. No fake terminal/command handlers.

First narrow terminal timing recorded in terminal-before.log. The required large_stream_pilot and larger terminal timing comparison are still in progress; initial pilot attempts failed before execution due unmatched reused environments, retained in logs and not called passes. NRA scan attempts likewise failed (first Python3.11 syntax, then missing Python3.14 tree_sitter binding); no completed global NRA scan or proof claim. This is an authored semantic move, not NRA-verified codemod replay.

Runtime source at initial draft +680/-711 (net -31). New behavioral/guard test is additional external-contract coverage; no preexisting terminal internal tests were found to port. Whole surface remains open until performance and real UI acceptance, dependency pairing and remaining guard review complete.
