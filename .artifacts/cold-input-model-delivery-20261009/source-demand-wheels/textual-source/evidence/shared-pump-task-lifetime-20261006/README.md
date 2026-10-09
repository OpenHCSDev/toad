# Shared message-pump task lifetime

Native73 left a real-entry cycle: run_test installed App._task, while run_async
entered App's replacement _process_messages with no task enrollment. A routed
pointer's completion could then bubble into its waiting App queue.

MessagePump._process_messages now owns actual task acquisition and release for
both App entrypoints and scheduled widget pumps. App supplies its existing startup
body through _process_messages_body. The test launcher retains only its local join
handle; Screen no longer clears task custody during its exit hook. Widget scheduling
still enrolls the original task before its coroutine starts, and never reinstalls
an eager task which has already completed. Timer/Worker/Markdown tasks are distinct
resources and stay with their original owners.

Original pointer completion, driver coroutine admission, capture, queues, shutdown
and selection boundaries are unchanged. No missing-task fallback or new queue,
timer, Toad override or completion exemption is added. App's duplicate body context
was removed; the shared lifetime borrows its existing polymorphic _context.

Existing refactor-audit Package parsed all 249 native production modules and
462 before / 463 after test modules, with zero omissions. before.json and after.json
record declaration and consumer coordinates. All App/Screen pump-task writes were
deleted; initialization, scheduled enrollment, acquisition and release now belong
to MessagePump. Independent Timer/Worker/Markdown tasks are included in lexical
results but retain their distinct owners. Dynamic external subclasses remain
unresolved explicitly.

## Actual entrypoint qualification

`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /usr/bin/python -m pytest -q
tests/test_real_app_pump_lifetime.py --tb=short`: **4 passed in 0.69s**.

The actual run_async/HeadlessDriver ingress delivered press, move, release and
wheel in order, including target-to-App bubbling and capture release. The actual
pump task matched its caller, cleared at pump exit, and child tasks joined. Other
cases covered startup failure, cancellation and eager completion without task
reenrollment. These are source App checks using the original driver and queues.
They do not use run_test to demonstrate real-entry task ownership.

Original collection refusal and test-assertion refusal are preserved. The latter
incorrectly assumed an inline run_async caller Task must finish when its borrowed
pump lifetime finishes. The corrected checks create and join the actual run_async
Task explicitly; no production or completion rule changed after that refusal.

The old 33 native73 controls and closed physical03 were not rerun. No installed,
physical, provider, package or public runtime operation occurred. The remaining
real-entry acceptance is Parent's actual terminal/Toad motion journey against the
matching source; the original physical03 cause remains unproved without a stack.
