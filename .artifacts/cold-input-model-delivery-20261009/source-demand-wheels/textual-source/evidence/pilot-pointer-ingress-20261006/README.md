# Pilot pointer delivery

Pilot now queues raw pointer packets on App and borrows the existing dispatch completion. App alone matches a press/release and supplies the final Click receipt and chain. Screen fills the original MouseEvent recipient when it actually routes through capture/current geometry; Pilot no longer keeps the first hit or authors Clicks. The gesture's screen coordinates are acquired after initial layout settlement and stay fixed across the press/release.

The existing completion future now carries the final message. Its release still occurs after dispatch and call-next work on the owning pump. Screen uses an offset event for its own delivery as it already does for child delivery, retaining the raw App packet's completion. A release consumes its press even if no click is admitted.

Current consumer/source evidence is in before.json (native production/tests and read-only Toad production/tests/tools; zero parse omissions). Arbitrary external subclasses/dynamic getattr are not resolved by lexical AST. The existing overridden test on_event now returns the original owner's result.

Changed-path source Apps are qualified, including the actual run_async/HeadlessDriver entrypoint:

- Driver + Pilot share one click chain/modifiers; an unmatched second release produces no click.
- A target moved by press or hover is not reported as the final recipient.
- Capture governs release delivery even when another widget is under the pointer.
- A completed click retains its recipient if that handler removes the widget.
- Blank Screen delivery retains the raw App completion, and the changed inherited on_event/copy/drag consumer passes.

The initial batch passed 160 checks (155 existing Pilot/click-chain checks and five new ones); one new Screen fixture assertion failed because its Horizontal covered the chosen point. The final five changed-path checks passed after moving the existing pause before coordinate acquisition rather than adding a delay. Its corrected blank-Screen fixture then failed only on an invented null Screen id; the original default Screen id is _default. The exact Screen-identity assertion passes separately (.71s), as does the changed inherited consumer (.83s). All three raw logs, both fixture negatives, and the original Batch05 evidence remain distinct. No production repair was needed for either fixture assertion.

before.json/after.json include the actual MouseEvent.widget declaration/reads/writes. Native 249 production, 465 -> 466 tests; dependency Toad 288 production/403 tests/40 tools, zero omissions. Static Toad event.widget consumers were read: GridSelect walks recipient ancestors; Store and Conversation use the original Click recipient; no on_event override requires migration. Driver coroutine/thread delivery remains unchanged. Batch05 is preserved: its Shift click reported true but selected only batch-a. No click-time geometry was retained, so this source defect does not identify its sole cause. No Batch05 replay, installed pin change, provider or physical run.
