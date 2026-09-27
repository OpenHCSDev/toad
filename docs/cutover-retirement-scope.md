# Toad cutover retirement inventory (default OFF)

`src/toad/acp/cutover_retirement.py` is an **in-process, cooperative Toad
incarnation** inventory, not an authorization token or production cutover
controller. `LIVE_TOAD_REGISTRY` observes Agent lifecycle after the disjoint
Agent.start/_run_agent/stop integration; merely importing it never pauses a
wire, writes a marker, stops a child, or changes routing.

## Hook contract

- Agent.start freezes its exact child environment/cwd and canonical root, then
  synchronously `register_pre_spawn(agent, pinned_root, implicit=...)` **before
  its first await**. A `RootFenced` denial must not spawn. Failed/cancelled
  preflight may mark NO_CHILD only after no spawn can occur; a stop while
  preflight is pending requires a final `_stopping` check before create_task.
- Agent._run_agent calls `mark_accepted(entry, AcceptedGroup)` synchronously
  after its accepted PID/start-time/PGID capture; never before capture and
  without an intervening await. It marks NO_CHILD only after the real
  admitted_spawn denial/cancellation cleanup has fully settled. An unreadable
  accepted identity is UNKNOWN and retains the strong Agent reference.
- Agent.stop calls `complete_normal_stop` only after fresh group retirement
  succeeds. Detached/unmounted sessions with unresolved children stay in the
  registry. Route-owned Agent.send/reconnect hook `require_open(pinned_root)`
  is a local synchronous fence, not a substitute for the core ingress lock.

A caller may synchronously `fence_old_root(root)` before requesting an
**externally authorized durable PAUSE**. `retire_enrolled` defaults to DENY
without both `assert_pause_current(root)` and
`assert_exclusions_clear(root, pinned_groups)`; it checks PAUSE around every
await, stops every enrolled accepted child, freshly verifies each original
process group, and rescans the live registry. PREPARED/UNKNOWN, unreadable
processes, survivor, changed inventory, stale fence or failed exclusion
assertion deny. The root fence must remain held through any externally
controlled EX route publication or withdrawal. The caller owns release after
abort/completion; release refuses any unresolved entry.

The returned `LiveIncarnationReceipt` binds Toad PID, PID creation time,
registry epoch and fence generation, and is **always `publishable=False`**.
It is invalid after process restart/fork, fence release, or PAUSE loss. It
proves only the enrolled same-PGID groups in that live Toad process. Escaped
children require separate OS containment/whole-host evidence, and unrelated
explicit-root/old-import clients require Codex operator exclusion. An empty
registry is not proof there are no old-capable clients. No production
MaintenanceBarrier begin/advance/token is available; disposable callbacks in
tests are *not* authorization. Cold supervised shutdown is a separate path.

No live process, saved session, pending/UNKNOWN input, provider dispatch, or
route publication is authorized by this slice.
