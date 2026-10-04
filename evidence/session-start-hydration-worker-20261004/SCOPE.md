# Startup and hydration execution ownership

Working source checkpoint; not installed Ready or a performance gain. Full UI/performance scope remains active.

- Conversation's written-source frame admits and binds the actual Agent synchronously. The original AgentProcess operation resource owns asynchronous Agent.start, across hidden/retained/evicted views, and its existing close/retire joins that operation. The input pump no longer awaits startup.
- CommsScreen admits hydration into its original native worker manager. Removed `_hydrate_queued` and `_content_loading`; its existing content admission and readiness event retain their contracts. Close and unmount cancel/join the actual hydration cohort before native teardown.
- AgentProcess admits Active disposition before preflight and checks that same owned disposition at commit. A close during awaited preflight cannot be overwritten by a late Active assignment and launch a runner. Existing route acquisition closes on that rejected commit.
- FramePresentation and WorkspaceSessions still own selected/attached/current-screen and writer admission. No universal callback worker, scheduler, task registry, startup timer, provider input, or public mutation was added.

Patterns: IMPL-13 (use the existing execution and retirement owner), AGENT-2 (close the whole related lifecycle rather than only the callback).

Before evidence uses existing refactor-audit Package across all 288 Toad and 249 native modules, zero parse omissions. Attribute/call evidence cannot resolve arbitrary external aliases or overrides. All exact startup/hydration callers and native worker/prune semantics were read. Native Tree cursor source is independently assigned to Kepler; no native edits here.

Validation last: one affected real App batch must hold actual startup/preflight and hydration resource work pending while verifying their own input/resize/frame delivery; then hidden return, cancellation and whole App close. Existing four #426 App positives remain scoped historical acceptance, not proof of this new path. Original failures/UNKNOWN inputs remain unchanged; no old movie repeat.
