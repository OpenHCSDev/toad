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

## Installed acceptance and remaining core blocker

Installed wheel on parent runtime-compaction-policy-b3a9c06, current Toad main and
Textual16ede: watcher_project_shutdown_pilot exits0 on actual /home/ts/.agent-comms.
Native registration is still incomplete at close (`native_ready_at_close: false`);
repeated Ready reuses the watcher, watcher+child join, asyncio/interpreter shutdown
completes normally. This directly closes the recursive-start shutdown defect.

Installed copied archived-history probe renders #comms(8), agent-comms-ux(2), and
pr95-selected-pi-summary-owner(0), with zero messages; watcher+child join. The full
probe still exits124 on a separate core task. Executor instrumentation identifies
HistoryViews.viewer_snapshot -> TranscriptReadLedger.counts -> view_unread._index,
still scanning saved native history at line125 after18s. Diagnostic trace retained
and assigned back to parent242. No core code changed or assertion weakened; this
is explicitly NOT a green overall archived-history exit.

Additional native cancellation test passes abrupt parent EOF during held recursive
startup, as well as actual file delivery, last-subscriber cleanup, shared surviving
subscriber and independent-directory registration. Burst coalescing retained:
500 events across14 recipients yield two batches/28 notifications with a later event.
No native model/ACP proof rerun, no paid calls, no live activation. Existing source
plus added ownership code is137 additions/78 deletions; the extra code owns process
lifetime/IPC because a Python thread cannot cancel watchdog's synchronous walk.

Parent may merge109 and pin its head independently of paired107 and the separate
core unread-scan cancellation. Paired107 receives this watcher correction too.
