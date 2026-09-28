# TR0 Toad collector — implementation and active full-suite triage

Own refactor/tr0-test-collection-20260928, based PR107 7e26f90.
Paired core PR254 a8e0d43, now pinned by pyproject.toml and uv.lock.

Implemented:
- One pytest collector derives *_pilot.py scripts; no hand-maintained command
  roster, no per-pilot adapter functions or rewrites.
- Each script executes as its real __main__ entry point using installed packages.
  Existing NamespacedChild owns deadline/retirement, including detached workers.
  Each script receives private state/cache/tmp/Comms/Pi roots. A private network
  namespace retains loopback fixtures while preventing real provider traffic.
- Timeout/nonzero exit fails once, with retained stdout/stderr. No skip/retry.
- Profile scripts moved to tools/performance; THREAD_WORKFLOWS command list and
  editable shared-root installation instructions deleted.
- Workflow definitions are manual only. Newest CI-deferred/no-gates directive
  supersedes TR0's original required-check sections; no protection API touched.
- Permanent machine-path/skip/old-script/manual-roster guards added.

Current evidence: 264 tests discovered, first real mounted IRC pilot passes
inside kernel containment and offline network isolation. Installed core console
has 11 passing real Git cases. Full suite is running with two workers; failures
will be classified against actual retained behavior before fixing or deleting.
This draft is code-bearing; full-surface readiness remains pending that triage.
No live state, provider requests or extra agents. Native244 support retained.
