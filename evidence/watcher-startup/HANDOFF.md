# Cancel recursive directory watcher startup

Independent of paired nominal-refactor PR107; based on current Toad main43e57c9.

PR107's small reuse correction only prevents a new DirectoryWatcher on repeated
Ready; it cannot cancel watchdog's synchronous Observer.start recursive os.walk.
This PR includes that correction and completes registration cancellation.

One process owns each path's native observer. The existing shared manager reuses
that observation until its last subscriber closes. Parent registration holds no
recursive filesystem IO or observer.start under its lock. Parent EOF ends the
child even during startup; bounded terminate/kill/reap handles teardown. IPC uses
nominal readiness/invalidation events over one owned pipe, with no shared-process
mutex that an interrupted child could strand. Existing UI event coalescing and
hidden-tab invalidation remain. No durable state, compatibility readers, deps,
provider calls, production runtime changes or refactor dependency.

Focused actual native test passes: synchronous inotify recursive walking held,
cancelled and reaped in0.013s; independent path starts and delivers real file
creation; two same-path subscribers share one process; one subscriber can close
while the other keeps receiving events; early stop spawns none; no child leaks.
Measured shared child RSS39.7MB. One child per distinct watched project, shared
across tabs; it ends when the last tab subscriber leaves.

Installed archive UI acceptance is in progress. It renders copied actual #comms
and both DMs without messages and confirms watcher+child have joined; full Python
interpreter shutdown is still under investigation and is not claimed green.
