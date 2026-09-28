# T7 terminal — source and local acceptance complete; paired activation remains

Lovelace, branch refactor/t7-terminal-20260928, own ~/wt/toad-t7-terminal-20260928 from fork main cc2d35c. User authorized this independent assignment while Darwin assembles243/244; combined native capacity acceptance preempts T7 when the package arrives. Read full T7, 00-RULES, 01-INDEX, 02-DISPATCH and NRA skill. Current open107/110/53/50 do not own ansi/; no competing T7 PR.

## Code and deletion

- Every ANSI command is a frozen slotted dataclass under public ANSICommand ABC and owns async apply (cursor response must await actual stdin). TerminalState retains primitive buffer operations; command match, forwarding handler and union alias deleted. Hidden output uses the declaration's visible_output property.
- All reads own feed; PatternRead shares incremental consumption. Parser generator yields reads only and emits parsed results through its existing stream owner. Deleted mixed yielded-type switch, unused cache/debug demonstration, regex buffer/max-length leftovers and EOF projection with no callers.
- Modes consume shared Comms DeclaredFamily directly. Numeric external declarations own mode changes; SetMode replaces optional feature/mouse bags and both hand-maintained enabled/disabled rosters. No aliases or local registry.
- Escape introducers use the same shared family. Terminated strings, designation, invocation and single-character payloads share inherited parsing. Deleted introducer match, DEC slots/invocation rosters and dead debug print helpers.
- External behavior corrections caught while moving the owner: OSC terminators no longer pollute link/path payloads; ESC / designation selects G3; IRM4 enables insertion rather than an ignored flag; disabling mouse encodings restores normal format. Unknown modes have no effect. External escape bytes and ACP/Pi formats are unchanged.

## Stores / cutover / dependencies

Only transient terminal buffers, parser reads, modes and declaration-derived registries. No durable store or format migration. New code depends on parent's round2 Comms DeclaredFamily (TD1); final pair/pin and quiet installation belong to parent. No live changes, providers or additional environment install.

## Local acceptance and exact limits

- `contracts-final.log`:44 pass on real TerminalState and reads, whole and byte-fragmented input; external cursor reply, styles/modes/scroll regions, unknown modes, OSC/DCS, new command/mode + collision refusal, consumption/exhaustion and AST deletion guard. No fake command handlers.
- `lint-final.log`: E/F/I source and contract lint passes. `git diff --check` passes.
- Existing `large_stream_pilot.py` passes on baseline fork main and refactor, actual mounted Toad App with input, live streaming, resize and end-sentinel assertions. Same fork Textual16ede007, Python3.14 runtime/dependencies reused, source snapshots only: Toad baseline cc2d35c and Comms d427425 (current pre-cutover native capacity branch). Parent's current round2 Comms/Toad107 pairing still owns retirement of main's old OBSERVATION_INTERVAL import; no compatibility export added here.
- The same pilot now includes actual terminal workload: three1,365,000-byte runs, bounded alternate buffer, exact rendered text. Baseline median5.293740s; final dispatch median5.173180s. Intermediate5.361761s was1.3% slower and is retained, not called passing; deleted forwarding dispatch and avoided unnecessary mode parsing before final comparison. Small local timing difference, not a universal performance guarantee. UI itself stayed bounded at105 message widgets, current maximum loop gap97.3ms (baseline101.5ms); resize/input/end assertions pass.
- Complete Python3.14 Toad source NRA scan returned in19.037s:191 parsed files,14 raw findings/9 active findings, none in ansi/. No mapping_read or unmodeled_record_shape raw findings were emitted. `nra-receipt.json` preserves coverage/timing and complete raw inventory; generated3.3MB analysis projection removed. External Comms declaration owner was read directly, not included in a cross-package proof. Earlier scanner/environment failures remain separate, not passes. This is an authored semantic move, not an NRA-verified codemod replay.

## Closure / stores / accounting

All T7 command/read/mode/introducer replacements and current ansi callers migrated; no old command bag/union/dispatch/alias remains. No preexisting terminal internal tests existed to port. Runtime +693/-725 (net -32); tests +255/-2, because the external byte contract previously had no terminal coverage. Full mounted pilot is retained and extended, not replaced by a mock or bypass.

Only transient terminal/parser/derived registry state; zero durable schema changes. No converter, live restart, provider call or environment installation. Temporary baseline source copies, generated scripts and pilot roots are removed after retaining text receipts. Parent owns final combined pin/wheel/live activation. PR114 remains draft for that integration, not a claim that these changes are installed.

Comms243/244 full CLI -> prepare -> journal/inherited-FD commit -> strict reopen acceptance stays the priority as soon as Darwin supplies the combined package; unchanged manager checks were not repeated.
