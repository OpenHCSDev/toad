# Agent-thread navigation and remaining startup delay

The app now lends navigation its existing admitted Comms service. A thread
request acquires one original RegistrySnapshot for thread identity, aliases
and status. Route changes, source identity, cancelled intent, and actual
backend attachment checks retain their original owners. There is no new
cache or cross-project ACP process sharing.

All five request constructors migrated. Before/after Package parsing covered
288 production, 407 test and 40 tool modules, with zero parse omissions.
Dynamic external callers remain unproved. Seven changed modules compile.
The existing cancellation/typing/closed-owner check passed after its original
conditional-expression coroutine caller was corrected; its unregistered
fixture-project menu warning remains preserved.

Real private four-view App checks passed source and installed route change,
incarnation retention, hidden prompt and closure behavior. The candidate
matches all 953 source/wheel assets, 69 package versions and 2856 RECORDs.
Only the three navigation production files differ from the installed Toad;
backend and all other package bytes remain unchanged.

One isolated st journey opened an existing saved agent thread, scrolled and
hid/restored its right panel, opened agent-comms-ux and returned to the
original tab. It completed with no submitted input, no cleanup errors and no
remaining owned process. Original output is at:
`/home/ts/.cache/agent-scratch/navigation-service-installed-agent-open-20261007`.

Its original frame trace records navigation at 2.02ms, mount/selection at
326.54ms, ACP initialize at 1896.96ms and session/load at 303.55ms.
Actual initialize request-send to response processing was 1895ms; this is
not server CPU attribution. Warm original-tab return took 32.39ms.
The readiness observer's 2139ms begins after its own acquisition and must
not be treated as total click latency. Snapshot/export waits also do not
measure UI response. This single run proves affected behavior, not an
overall performance improvement. ACP cold startup remains a concrete gap.

Build/proof and publication evidence stays in the existing worktree at
`.artifacts/navigation-service-wheel-20261007`.
