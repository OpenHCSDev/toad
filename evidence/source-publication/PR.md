# Operational source activation and native-page publication

Continuation of merged175/116/110 in the same owned persistent worktree. Final latency target remains unfinished.

Existing CoordinationTranscriptReader.bind incorrectly holds the service initialization lock through every caller's awaited status/owner/page projection. Release only that binding lock after capturing the exact canonical Comms service. Store-owned canonical locks and every existing source/current read fence remain. No additional cache, state mirror, roster or reader.

AgentController.restore now publishes retained configuration/modes/commands/typed plan/queue/cursor before awaited native-page I/O, rather than blocking these facts behind the page. Saved history publication captures existing SurfaceBinding and SessionBinding identity and rejects replaced sources/sessions after the read. Existing terminal owner remains responsible for terminal presentation.

Delete the old page-first control publication block and consumer-spanning lock scope. IDEN-1/IDEN-7/IMPL-10/TIME-9 ownership: service initialization belongs reader, transactions belong canonical stores, operational controls belong controller, UI publication requires captured session/source identity.

Actual acceptance in progress: existing continuous installed App/Pilot/ACP/native saved-state journey extended with a real exclusive GoalWaits store lock. It must deliver a native page while the unrelated thread-status projection remains blocked, without mock readers/transports. Preserve all original body/reader/draft/undo/raw-read/idle/End/fork/channel paint assertions and process EXIT0. Baseline/final receipts will be published.

Resource cleanup: removed only verified inactive completed predecessor-install/wheel copies (~6MB); retained source, evidence and current candidate. One bounded fixture at a time, no duplicated cohort matrices. Parent owns paired default install/live gate, untouched. No speedup/50ms/terminal-writer completion claim. Native107378 integration will follow parent-published paired authority; default native d396 used by current fixture.
