# Refresh callback execution belongs to its sender

Screen retained each callback with its sender, checked that sender's paint, then
awaited the callback on Screen's task inside the sender's context. An async
callback could wait for its sender's next refresh: wait_for_refresh saw a foreign
task, queued another Screen callback, and waited while Screen was still awaiting
the first callback. One async widget callback could also prevent unrelated
senders' paint and callback admission.

Screen now owns admission only. It hands each admitted callback to the sender's
existing call_later / events.Callback / on_callback path. That original pump owns
execution, self-wait refusal, errors and teardown. No new task or queue is added.
Held callbacks remain in Screen's same queue; the original subtree, whole-frame,
batch and backdrop checks remain. One synchronous drain borrows one preparation
cohort; the repeated preparation and foreign callback context/invocation were
deleted. No preparation is acquired for an empty or batched callback queue.

Existing Package parser covered 249 native production modules, 463 native tests
and 288 Toad dependency modules with zero omissions. before.json records 208
lexical declaration/consumer sites. External dynamic callback targets remain
unresolved. Toad sources were read, not edited.

This source defect is not established as physical04's cause. The original footage
shows saved transcript paint. A callback held behind native readiness does not
itself suppress the capture helper's independent asyncio timeout; its missing
DTO/error still needs Parent's helper trace. Original recordings, helpers,
wheels and failed capture remain unchanged.

## Changed-path qualification

`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /usr/bin/python -m pytest -q
tests/test_refresh_callback_owner.py tests/test_lazy.py::test_lazy
tests/test_reparent.py::test_reparent_preserves_order_and_transfers_pending_frame_callbacks
--tb=short`: **5 passed in 0.79s**, terminal exit 0.

The three new real run_async/HeadlessDriver cases confirm App/widget callbacks run
on their own actual tasks, retain the original self-wait refusal and allow another
sender's actual paint/callback while suspended. Held subtree, Screen and App
callbacks remain queued until the original roots release. The two existing cases
cover the directly affected async Lazy mount/self-removal and original queued
callback transfer on reparent. No old native73/74 or physical check was repeated.

after.json covers 249 native modules, 464 tests and the same 288 read-only Toad
dependency modules, zero omissions. Screen's foreign invocation/context were
deleted; original MessagePump.on_callback is now the shared execution consumer.

No installed, terminal-writer, Toad physical or provider run occurred. Original
writer hooks/receipts were not edited; actual matching Toad/terminal acceptance
and the original missing capture response remain unqualified. All test App tasks
returned; no process or runtime was left running.
