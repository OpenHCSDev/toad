# Terminal failure capture, not a recursion fix

Current base19de70ca; own CLI boundary only. Parent core3261906/runtime-channel-participants remains untouched. Tesla142 owns App/workspace and Noether145 rendering. Coordination:142 comment5882612784.

## Verified failure boundary

Installed Textualc974 App._handle_exception stores the original exception, prints a Rich traceback, and shuts down. Ordinary App.run returns instead of rethrowing this UI exception. Existing ACP logs record protocol traffic and cannot retain that terminal failure. No authentic user crash stack found; original crash remains unresolved. No inference about old instances.

CLI now owns running, retaining uncaught/escaping failures, and success-only run_on_exit. Both normal and acp launch callers consume run_terminal; duplicate run/run_on_exit sites deleted. Persist plain Python traceback without local variables in existing paths.get_log(), using existing ACP filename authority. Exclusive owner-only file; terminal error retained and process exits nonzero. Storage errors are reported without hiding original failure. No App override, new log registry, background writer, transcript copying, recursion-limit change, or exception fallback.

## Latest patterns

Both NRA/refactor-audit skills reread; actual refactor-audit archive2216. IMPL-12: one CLI terminal procedure replaces duplicate launch sites. IMPL-4/5: both callers migrated, no partial dispatch. TIME-9: no adapter/codec or alternate wire form. AGENT-8: actual terminal proof, no mock App.run. IDEN-1/3 and IMPL-10 reviewed; no compound identity/absence/lifecycle chain added. IMPL-14 rule family is unnecessary for this single exception boundary. Product CLI boolean chain-term delta0, class-size delta0.

## Evidence

Noneditable installed own wheel, inherited paired core1906/Textualc974. Actual PTY terminal driver, real ToadApp mount/render, controlled callback RecursionError: prints error, exits1, leaves exactly one600 file containing original failing callback/traceback after process exit. This is capture verification, NOT reproduction of user's recursion. First isolated environment lacked agent_comms before startup; failed receipt retained, environment corrected.

Actual installed private native send/source-return pilot FAILED exit1: attached/navigation succeeded, first new FIRST_NATIVE_INPUT reached session/prompt and turn_started, then settled end_turn without loopback request; entered.is_set wait timed out. No RecursionError. This does not establish send/source-return acceptance. Parent owns core diagnosis if needed; no speculative capture patch added. Local loopback model only, no existing input replay or paid calls. No live launchers/history/owners changed. Parent controls deployment.
