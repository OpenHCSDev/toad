# Original installed fixture cleanup closure

Owner: Einstein. Scope: `tests/runtime_fixture.py` cleanup in `ToadApp.run_test`.
Kepler251 owns physical driver controls; Heisenberg252 owns product Sidebar source.

Original m01/u04 failures show the extra OS process wait raising after canonical
owner stop returns, preventing remaining fixture child and lock cleanup.
Core458 installed29 preserves both actual terminal failures, input-free source,
and custody receipts. The original worker's state at the wait instant was not
captured; this is not evidence of a native turn stall.

Use the existing Python asynchronous exit stack to complete all original cleanup
operations in their existing order and retain the original exception chain.
No product code, timeouts, native/provider/input replay, metadata or package/default
changes. Existing controls and public source remain protected. This draft is a
fixture contribution for the next coherent driver; it does not establish user UI
readiness and must not hold concrete Sidebar source fixes.
