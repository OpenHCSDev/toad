# Primary Screen selection gesture

Screen alone admits its pointer selection range on a primary press and ends it on a primary release. Secondary input continues through the original recipient/capture/focus/menu route; it cannot start or end Screen's primary gesture or emit its TextSelected boundary.

The existing primary press offset and pointer range now supply _selecting. Deleted its separate reactive value and writes, including the range-projection assignment which could revive a released gesture. The original press/range watchers stop the existing auto-scroll timer when either custody or range retires; the timer callback borrows the same active gesture. The range remains available after release for copy and layout projection. Screen suspension retires the press too: its release will route to another Screen, so the covered Screen cannot retain auto-scroll custody. Copyable ranges and pending projections remain intact.

Input/TextArea own separate editor selection and capture models; this change concerns Screen's selectable-content range. Toad/visual consumers read _selecting and need no alternate state or API. before.json uses the existing Package AST across native production/tests and read-only Toad production/tests/tools; dynamic external subclasses remain unresolved.

Qualified source App scope:

- A secondary edge drag acquires neither a selection nor its auto-scroll timer.
- Secondary release during a primary drag preserves its range, primary press and completion ownership.
- Actual run_async/HeadlessDriver primary edge movement scrolls through the existing timer; primary release stops it and range projection cannot revive the gesture.
- Right capture/release and a real pushed menu deliver normally while preserving completed primary text.
- Screen suspension stops active primary scrolling; returning retains copyable text without resurrecting the press.
- Existing selection/copy/coalescence and endpoint-retirement checks pass.

Initial batch: 24 passed, one authored run_async fixture failed (26.72s). Source shows its mounted callback preceded resized arrangement; the fixture tried to scroll before its original max_scroll_y was available, so the requested row was not its actual press target. The corrected fixture borrows the existing publication before scrolling and asserts scroll/recipient identity: that exact control passes (1.21s). The separate changed Screen-suspension control passes (1.19s). The production press/move/release correction was unchanged by the fixture repair. Both logs remain preserved. No passing controls were repeated for count.

before.json/after.json: 249 native modules, 466 -> 467 tests, dependency Toad 288 production/403 tests/40 tools, zero omissions. Screen/visual/Toad readers derive activity through the same property; no writer or reactive subscription to Screen._selecting was found. Toad suspension consumers keep their original base behavior. Input/TextArea names are distinct owners, not competing Screen facts. This is a source counterexample; no sole physical/menu causal claim. Frozen a59/2d wheels and the prepared menu02 App remain unchanged. No package, installed pin, provider or physical operation.
