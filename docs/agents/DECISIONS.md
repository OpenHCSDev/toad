# Decisions

## 2026-10-09: History becomes one line-based view

### What a frame costs today

Evidence: the retained 12-second profile of the last real run (`accepted-geometry-real-wheel.speedscope.json`, held wheel input on Tristan's saved session, Toad f9b062d with Textual 66e91ec), its state exports, and the source.

The UI thread was busy for 8.2 of the 12 seconds. The last comparable frame measurement was a 246–327 ms median frame interval: three to four frames per second. Only 215–462 widgets were mounted, and 73–87 of them were visible. Upstream Textual handles a tree that size well inside a frame, so widget count is not the cost. The cost is the machinery that swaps messages between live widget trees and retained paint as they scroll in and out.

Share of UI-thread time during the wheel run (shares overlap because they are inclusive):

| Work, per frame | Owner | Share | Why it exists |
|---|---|---|---|
| Re-arranging layout on the screen timer tick | `WorkspaceScreen._refresh_layout` → Textual `_compositor.reflow` / `arrange_widget` | 22% | Bodies mount, materialize and retire while scrolling, so layout is invalid on most frames. Toad's anchor compensation can run the reflow twice. |
| Recomputing paint admission | fork `DocumentPresentation.acquire_admissions` / `current_admission`, Toad `ViewportPresentation.using_document_inputs` | 13% | Each frame, every admitted document rebuilds a tuple of CSS state for every node on its ancestor path to prove its cached paint is still valid. |
| Materializing bodies | `BodyMeasurement.materialize` (`viewport_body.py:238`) | 12% | Messages entering view are rebuilt from retained paint into native Markdown widget trees. |
| The frame gate | `ViewportPresentation.prepare` (`_prepare_compositor_refresh`) | 10% | Walks exposed bodies and their ancestors against every mutation root, to decide what may be painted. |
| CSS pseudo-class and style lookups | Textual `get_pseudo_classes`, reactive and style getters | 10% | Called from all four rows above, once per widget per check. |

Every row exists because each message is a widget subtree that must be built, measured, retired and restored. That is also why there are ten body states in `viewport_body.py` (2,549 lines), and why the Textual fork grew by 9,849 lines over v8.2.8: 2,090 lines changed in the compositor, plus a new 1,284-line `document/_paint.py`. The stopped six-file diff removes some eager waits, but it leaves every row in place and adds three more distinctions.

### Decision

Replace the committed-history widget tree with one line-based view: a `ScrollView` whose `render_line(y)` returns rows of strips already prepared by the existing render worker processes (`MarkdownDocumentRenderTask` in the `ProcessPoolExecutor`, which already runs off the UI thread and outside the GIL). Only the streaming tail, the input box and the sidebars stay ordinary widgets. The stopped six-file diff is preserved on a `wip/` branch and not continued.

Rejected: keeping per-message widgets and deleting only the per-frame machinery. Saved history is 141 MiB, so it must be paged in while you scroll, and mounting Markdown widgets is UI-thread work in Textual: construction, CSS and layout. A held PageUp into unloaded history would still stall on every page mount. The line view never mounts anything while scrolling.

### Frame budget and why the design can meet it

The budget is p95 total UI work per frame of 16 ms or less, and input-to-paint p95 of 33 ms (two frames) or less.

A scroll frame in the line view does three things:
1. Changes the scroll offset.
2. Calls `render_line` for about 45 visible rows; each is a list index plus `Strip.crop` on cached strips.
3. Has the compositor render that one region and the driver write it.

It does no layout, because the virtual height changes only when a message's line count changes, and no per-message CSS or paint admission. That is the same path Textual's `Log` widget uses for large content, and it costs low single-digit milliseconds for a viewport of this size. All five rows of the table above disappear from the scroll path, and together they cover essentially all of the measured busy time. The first increment measures this instead of assuming it.

Requirements carried by the design:
- **No blank rows:** a message whose styled strips are not ready renders its plain wrapped text synchronously, which is cheap, and is replaced when the worker result arrives. It is never a placeholder.
- **End:** scrolls to the virtual end.
- **Tab return:** strips are kept per width, so returning only paints.
- **Width change:** re-prepares visible messages first, in the workers.
- **Clicks and disclosure:** use style metadata on the strips, mapped back to the message; a toggle re-prepares that one message.
- **Selection:** the selected text comes from the source text of the lines.

### What will be deleted

- **In Toad, once the line view carries history:**
  - the body-state machine in `viewport_body.py`;
  - `presentation_window.py`;
  - the page and fragment views in `transcript_history.py`;
  - the widget-versus-paint dual paths in `prepared_markdown.py` and `streaming_markdown.py`;
  - the `WorkspaceScreen` frame hooks.
- **In the Textual fork:**
  - the presentation hooks in `Screen` and the compositor (`_prepare_compositor_refresh`, `_layout_mutation_roots`, `_using_presentation_inputs`, `_on_frame_published`);
  - the admission half of `document/_paint.py`.

  The strip-producing part stays as long as the render workers use it.
- The series table records lines added and deleted for each increment.

### Measurement gap found

`tools/performance/capture_live.py` profiles and exports state, but its frame trace records only the driver's writer. It cannot produce total UI frame time or input-to-paint latency. The first increment extends its existing observer to time UI-thread work between writes and the delay from each input event to the first write after it is handled. No new tool.

## 2026-10-09: What the measurements showed, in order

- **The frame gate froze the screen.** `ViewportPresentation.prepare` withheld the history window's paint until every exposed body was ready. Inputs were handled within milliseconds, but frames carrying their effect were held for seconds. Removing the deferral took the run from 90 frames to about 2,900 in 45 s.
- **The App's message pump waited on coordination re-reads.** Every `CoordinationObserved` event awaited a 200–550 ms registry and channel read inside the App's handler, 7.6 s of a 45 s run, and every key and wheel event queued behind it. It now runs as one background pass at a time.
- **The UI thread is saturated, not waiting.** py-spy's default sampling hid it. With idle samples included, the thread is in `select` only 10% of the time. The largest inclusive costs are pull-based paint validation: the fork's `current_admission` (22%), CSS pseudo-class computation (16.5%), and body readiness checks (13–14%). Scrolling itself is cheap. This confirms the line view: its lines are rendered once with the theme's colors and invalidated only on a theme or width change, so nothing is re-proved per frame.
- **Run-to-run noise** on this live system is about 3 ms of frame p95 and about 1 s of input-to-paint p95, because the comms bus traffic of about 20 running agents varies. Single captures within that band are not evidence either way.

## 2026-10-09: State after publishing the line view

**Published:** the five default commands point at `~/.local/share/agent-comms/runtimes/toad-lines-9eb0042` (Toad 9eb0042, Textual 66e91ec, Core bdb8df4 with `user-send`). Through the default `toad`: frame p95 9.8 ms, p99 20.2 ms; input-to-paint p95 28 ms, p99 40 ms. Under a real `#openhcs` load (nine agents replying during the run): frame p99 27.8 ms, input-to-paint p99 87 ms. Tristan's target is now **p99 at or under 16 ms**.

**Finding the slowest frames:** `frame_meter.py` records, for each frame over 16 ms, the callbacks that filled it, labeled by owning timer, worker or widget.
- The history lookahead read `page.size`, and in this fork reading `size` on stale layout forces `reflow_visible`. Fixed in the working tree: pages expose `line_width` and `line_count` from their own layout. Not yet committed, because its measurement was confounded by concurrent comms load tests.
- `SessionAdmissions._retire_requested_views` re-reads the registry and channel catalog and resolves routes on every `CoordinationObserved`, which arrives on nearly every bus change. The durable fix: the coordination observer reads once per revision and publishes what it read, and consumers derive from that. That is a migration across every consumer of the event.

**Next durable step (#60):** move the live tail onto the same line owner. `PreparedConversationMarkdown` (behind the streaming response, thinking and the user, incoming and outgoing bodies) and `ToolContent` are the only users left of `MeasuredViewportBody`, the body-state machine, `DocumentViewport`, the `WorkspaceScreen` frame hooks and the fork's per-frame paint admission. Once both draw prepared lines, delete that whole lattice in one change.

**Durability for other frontends:** line blocks currently embed Rich `Style`s. They should carry semantic roles (divider, user body, agent body, tool summary, notice) mapped to styles by a frontend-owned theme, so another terminal backend renders the same blocks.

**Known gaps in the line view (to restore, not to forget):**
- Text selection and copy in committed history.
- Expanding tool output and the agent coordination context from history (they draw as one-line summaries).
- User messages draw as plain text, not Markdown.

## 2026-10-09: Plan for moving the live tail onto the line model

**How live messages paint today** (mapped from source):
1. `PreparedConversationMarkdown._update_body_source` parses and acquires a fork `MarkdownDocument`.
2. `_prepare_document` submits `MarkdownDocumentRenderTask` to the render workers.
3. The widget becomes a dormant `PreparedDocumentBody`, and `render_lines` crops the worker's `DocumentPaint`.

Real Markdown block widgets exist only for non-conversation parsers, or after a MouseDown (`App.prepare_input` → `materialize_document`). The per-frame admission (`using_document_inputs`, `acquire_admissions`) only caches the paint-validity check for one frame. Without it, `current_admission` is checked live, which is slower.

**Consumers to migrate:**
- `StreamingMarkdown`: `AgentResponse`, `AgentThought`.
- `UserInput` (`user_input.py:69`).
- `MarkdownContent` (`tool_content.py:37`).
- `ToolContent` (`tool_call.py:38`): `MeasuredViewportBody`, used only for offscreen retire and restore.
- `file_kind.py:58`, `project_panel.py`.
- Readers of `document_viewport` and body readiness: `irc_message.py`, `session_view.py`, `transcript_source_preparation.py`, `mounted_message_history.py`, `transcript_state.py`, `session_presentation.py`, `setting_effects.py`, `app.py:546`, `conversation.py:331,524`, `history_anchor.py`.

**Features to carry over, not drop:**
- Per-block cursor and copy, including code fences (`block_navigation.py` `DocumentBlockCursor` / `ChildBlockCursor`).
- Anchors and table of contents (`paint.anchor_region`, `paint.headings`).
- Text selection.
- Clicking links and project paths (parser features; click needs a hit target).
- Custom grammar parsers.

**Shape:**
- **One line-drawn Markdown widget** replaces `PreparedConversationMarkdown`, used for live and committed text alike. It renders `Body` blocks through `RichLineRenderer` in the render workers and draws plain rows until the styled rows arrive. Streaming appends coalesce, with one render in flight. No paging is needed, because lines are cheap.
- **Interaction lives on the line model.** Blocks know their row ranges, so cursor and copy, anchors, selection (`get_selection` from block source text) and links (style metadata mapped back to a block) are implemented once, for history and the live tail alike.
- **Then delete, in one change:**
  - `viewport_body.py` (`ViewportBody`, the `BodyMeasurement` family, `DocumentViewport`, `ViewportPresentation`);
  - `presentation_window.py`;
  - the `WorkspaceScreen` frame hooks;
  - the fork's `document/_paint.py` admission, `document/_markdown.py` and the `widgets/_markdown.py` detached-document additions, plus the Screen and compositor hook call sites.

  Two hooks have side effects that need a new owner first. `_prepare_compositor_refresh` calls `check_follow()` every frame, which should move to the window's own scroll/size owner. `_layout_mutation_roots` holds a `HistoryWindow` subtree during `preserve_history`; check whether line pages still need that hold.

## 2026-10-09: Live tail on lines: built, not yet merged

The live-tail migration is on branch `wip/live-tail-lines` (`e37ae09`, +329/−3735).
- **Messages now draw through `LineMarkdown`:** `AgentResponse`, `AgentThought`, `UserInput`, tool Markdown and the file preview.
- **Deleted:**
  - `viewport_body.py`: body states, `DocumentViewport`, `ViewportPresentation`;
  - `prepared_markdown.py`, `streaming_markdown.py`;
  - the dead `incoming_message.py`;
  - the `WorkspaceScreen` frame hooks;
  - the source-retention plumbing.
- **The history window owns** its lookahead, budget, destination and preparation requests.

It runs the fixed scenario with no crashes. Measured frame p99 was 22.6 ms against 16.5–19.4 ms on `perf/line-history`, and input-to-paint p99 41.6 ms. Those runs overlapped the latency subagent's `#openhcs` test traffic.

**Next:**
1. Compare both branches back to back on a quiet system: two runs each, same display.
2. If the live tail is slower, attribute its slow frames. During streaming, each fragment relayouts the conversation, and styled restyles are paced at 0.25 s (`LineMarkdown.RESTYLE_INTERVAL`).
3. Merge only if it holds.

**Still open after the merge:**
- Delete the fork's detached-document system (`document/_paint.py`, `document/_markdown.py`) and its Screen and compositor hooks.
- Restore the features listed in the plan above: block cursor and copy, anchors, selection, links.

## 2026-10-09: Deletion pass

- **Merged the live tail on lines** (`c9af698`). Back to back on a quiet bus, frame p99 holds (18.8 / 19.4 ms against 17.8 / 18.9 ms), input-to-paint p99 improves, and frame p95 is about 3 ms worse. That p95 cost is unexplained, and is the first thing to attribute.
- **Deleted the unreachable Markdown preparation chain** (`6de8363`): `PreparedMarkdown`, `PreparedFence`, `PreparedContentRange` (the page now owns its own admitted range), the Markdown render tasks, `DocumentBlockCursor`, and the fragments' preparation fields, `prepare()` and `independent()`. Fragments no longer carry parsed tokens back from the workers.
- **Toad references nothing from the fork's `textual.document._markdown` or `_paint`** (`f483186`).
- **The fork deletion is delegated:** `document/_markdown.py`, `document/_paint.py`, the detached-document additions to `widgets/_markdown.py`, and the Screen and compositor presentation hooks Toad no longer overrides. It goes on fork branch `perf/line-history`, verified with one scenario run.
- **Measurement hygiene:** runs that overlap the comms latency work's `#openhcs` test sends aren't comparable. Measure performance only on a quiet bus, back to back, two runs each.

## 2026-10-09: Load, fallbacks and Core owners

- **Every measurement runs under `#openhcs` reply load.** p99 under quiet conditions is not the target.
- **Shared caches belong to the file, not the store object.** The decoded registry and the activity log's read state each belong to their file, shared per process (Core `b1e6ec85`, `f74c82b`). Each `Comms` used to rebuild its own copy, decoding up to 5 s of data on Toad's executor threads and starving the UI of the GIL.
- **No fallbacks that hide defects** (Tristan). `_offset`'s `virtual_region` fallback had hidden that the off-screen anchor declaration was deleted along with the body machinery. The screen declares it again (`_layout_geometry_targets`), and unplaced anchors now raise. Core's masking handlers were removed (`78731e19`). That removal exposed a left-behind abstract hook that stopped ACP sessions starting; it is fixed at its owner (`46b3e8f`).
- **Comms logic belongs in Core** (Tristan). Toad asks Core: `WireRevision.registrations_changed_since` drives view retirement. Prompt-send admission (`acp/maintenance_ingress.py`) is moving into Core with an API that does not block the UI thread.
- **Thread deletion** is `agent-comms delete` on Core branch `feat/thread-delete`. Every per-thread store declares its removal, and append-only logs get a deletion record, never a rewrite. Hold further live deletes until a runtime that understands that record is installed.
- **Open live defect, not caused here:** `openhcs-audit-merged-boundaries` and `openhcs-audit-merged-models` have stopped inbox drains ("Selected source requires reviewed raw-history coverage floor"; diagnostics under the live root's `diagnostics/drain-*.json`). This belongs to the compaction owner.

## 2026-10-09: Stopped. Frame p99 under load is not converging; what I learned

Two consecutive increments (the throbber at 15 fps; fixed-size status lines) cut real work, about half the frames and about 35% of the layouts, without reducing slow frames. Under `#openhcs` load the fixed scenario still has about 65 frames over 16 ms per 45 s. Following the goal's rule, I stopped here.

**What the measurements show**
- **Bursts, not load.** The UI thread is busy only about 8.8 of 40 s under load (py-spy). Slow frames are bursts: everything queued since the last paint runs before the next one.
- **What a typical slow frame contains** (about 21.5 ms):
  - painting, about 4.4 ms;
  - the footer, about 3.5 ms when bindings change;
  - conversation and ACP message handling, about 3.5 ms;
  - waiting for the GIL, about 1.4 ms;
  - many sub-millisecond callbacks.
- **No single owner dominates any more.** The stall sampler (8 ms threshold) finds no Toad stack repeating.
- **Full-screen layout is the largest Toad-reachable cost:** `WorkspaceScreen._refresh_layout` is about 1.8 s of the 8.8 s. Textual can only lay out the whole screen, so each content-size change re-arranges everything.
- **Per-frame percentiles are a misleading target.** They change with the frame mix: removing about 1,250 nearly empty animation frames raised p95/p99 while total work fell and input-to-paint improved. Use the count of frames over 16 ms per minute of the fixed scenario, or the UI thread's busy time per 16.7 ms wall-clock window. Those do not move when cheap frames are added or removed.

**What I would change next, in order of expected effect**
1. **Measure jank as the count of over-16 ms stalls per minute under load,** reported next to input-to-paint. The goal's p99 should be stated in those terms.
2. **Incremental layout in the Textual fork.** When a widget's outer size is fixed (the window, a sidebar row, the status lines), a change inside it re-arranges only that subtree, not the screen. This is a compositor change in the fork with real risk, and it is the structural cut for about 20% of UI CPU.
3. **Move Core reads out of Toad's process** (a Core read service in a worker process, like the render workers), so background Core work stops competing with the UI thread for the GIL.
4. **Footer:** rebuild only the keys that changed instead of remounting the footer when bindings change.

## 2026-10-09: Second approach measured and stopped (Tristan's rule: two failed approaches, stop and write a page)

**Approach 1: cut work at its owners.** Throbber cadence, fixed-size status lines, and the GIL switch interval. This reduced total frames by half, layout requests by 35% and GIL waiting by about 10 points, and improved input-to-paint, but did not reduce the roughly 60 frames over 16 ms per 45 s loaded run. The changes are kept because each removes real waste; reverting would bring the waste back. That is a deliberate departure from "revert".

**Approach 2: structural layout and frame-rate changes,** measured before building:
- **Layout:** 45 of 59 slow frames contain a full-screen layout, 25% of their time; without it, 30 of 59 would fall under 16 ms. But only about 45 widgets are placed per layout. A deterministic profile of 40 to 60 real layouts puts the layout's own CPU at a few milliseconds each. cProfile in Python 3.14 instruments every thread, so its larger numbers include background work. Partial (subtree) layout in the fork would save a few milliseconds per layout and is not worth a compositor rewrite. Not built.
- **Frame cap at 60 instead of the fork's 144** (`TEXTUAL_FPS`): 56 and 64 slow frames over two runs, unchanged; percentiles rise as frames get fewer and fuller. Not adopted.

**What a slow frame is under load:** about 21 ms made of many items of 0.5–4 ms:
- painting, about 4.4 ms;
- layout, 2–8 ms when present;
- ACP stream and conversation messages;
- the footer;
- timers;
- waiting for the GIL behind executor threads doing Core reads, 11–18%.

No owner left in Toad is worth more than a few milliseconds. The UI thread is busy about 22% of the time; slow frames are bursts where several of these items land between two paints.

**What would change the count** (needs Tristan's decision; none is a small step):
1. **Restate the target as stutter rate,** for example frames over 16 ms per minute of the loaded scenario, with input-to-paint. Today's per-frame p99 moves when cheap frames are added or removed.
2. **Take Core work out of Toad's process:** a Core read service in a worker process, as with rendering. This removes the GIL competition (11–18% of slow-frame time) and the executor threads' interleaving with UI callbacks.
3. **Coalesce the per-update fan-out:** one coordination observation currently triggers sidebar, activity, goal bar, footer, session details and conversation work separately. A single per-frame presentation pass driven by Core's revision would turn many small callbacks into one bounded step per frame.

## 2026-10-09: Decompose comms semantics out of Toad (Tristan)

**Targets:**
- Worst frame at or under 16 ms in the loaded scenario; measure it as the worst frame plus the counts over 16, 33 and 50 ms.
- Toad becomes generic UI infrastructure, with comms UI semantics behind an interface a future PyQt reactive backend can implement.

**OpenHCS precedent** (`external/ObjectState`, `external/pyqt-reactive`, `python_introspect`, `metaclass_registry`):
- `ObjectState` owns state, independently of windows.
- Views subscribe to changed dotted paths and flush once per event-loop turn.
- Forms are derived from declarations.
- Paint is derived from time.
- Packages split by what they know.

Not copied: pyqt_reactive's string action tables (`ACTION_REGISTRY`, `BUTTON_CONFIGS`); actions stay declared families.

**Layers:**
1. **Core (`agent_comms`):** comms meaning, plus revisions answering what changed.
2. **`comms_ui`:** a new package in the agent-comms repo with no Textual or Qt imports. It holds typed presentation state per scope (thread, channel, session tab, sidebar, goal, queue), updated from Core revisions as changed-path sets, with per-path subscriptions and one flush per frame. Actions and forms come from Core's declarations.
3. **Backends:** Textual (Toad: line rendering, history window, prompt, tabs, frame budget) and later PyQt.
4. **Shared generic library:** `declared_family`, `mro_dispatch`, `field_codec`, reusing `metaclass-registry` and `python-introspect` where they cover the same meaning.

**Order:** vertical slices, each measured in the real app and each deleting Toad's old path in the same change.
1. Sidebar.
2. Status bars (session details, goal bar, footer, queue).
3. Conversation and transcript.
4. Core reads in a worker process feeding `comms_ui`.
5. Forms from declarations (goal edit, fork, settings, thread actions).

## Current goal (2026-10-09; for /goal)

1. **Worst frame:** at or under 16 ms in the loaded scroll scenario, run through the `toad` on PATH with `#openhcs` replies arriving during it. Report the worst frame, the counts over 16, 33 and 50 ms, and input-to-paint p95.
2. **Screen checks:** `tools/performance/screen_checks.py` passes.
3. **Comms meaning:** comms meaning lives in Core. The comms UI semantics live in a frontend-neutral package with no Textual or Qt imports, and Toad only renders it. Each migrated slice deletes Toad's old path.
4. **Publication:** published to the default runtime, with agents restarted, and recorded in `docs/performance/scroll-series.md`.

**Order:**
1. Sidebar (done).
2. A Core observation service out of process (done: sidebar, open-thread status, turn settlement, view retirement).
3. Conversation and transcript reads in the service (in progress).
4. Forms from declarations.
5. The remaining worst-frame owners.

**Rules:**
- No approval steps.
- Fail loud.
- Comms logic never lives in Toad.
- An approach that does not improve its measure after three increments is reverted or replaced. Stop and write a page only after a second failed approach.

## 2026-10-09: The sidebar slice landed; observation moves out of process next

- **Sidebar slice:** the sidebar renders Core's `ui_model` (Toad `ecfa7de3f`, Core `f5277b8f0`). Toad lost 1,312 lines (four sidebar modules) and gained 641; 9,001 lines of tests for the deleted machinery were deleted; the shared helpers moved to the model API.
- **Goal display:** moved to `agent_comms.ui_model.goal`.
- **Status rows:** `ui_model.status` holds the status rows for open threads.
- **Finding:** each view re-reads or recomputes on every 50 ms observer tick. That covers the status line, the turn settlement and transcript refresh that share its read, the slash-command catalog, and per-second goal polls. `CoordinationAccess.observe` itself makes two or three worker-thread round trips every 50 ms, even when nothing changed. These wake-ups and executor threads are the many small callbacks and GIL waits in slow frames.
- **Decision:** the next slice is a Core observation service in its own process. It watches Core's stores (`wire_watch`), recomputes `ui_model` models only on real changes, and sends small typed change sets (sidebar rows, open-thread status rows, presentations for turn settlement). Toad applies them through one pipe reader with one flush per frame, and deletes its poll loop and per-view reads. The status wiring lands directly on this service instead of on the poll loop.

## 2026-10-09: The observation service landed; remaining worst-frame owners

**Landed:**
- **Observation service:** replaces the 50 ms poll loop. Slow frames fell from 88–91 to 48–54 per loaded run; frame p95 is about 15 ms; input-to-paint p95 is 12–15 ms.
- **View retirement:** runs in the service. The scenario now deletes its open fork and checks that the tab closes.
- **Batched history rendering:** one round trip per batch instead of about six loop callbacks per fragment.
- **`Widget.size`:** computed from the widget's own size and gutter (fork), not looked up in the compositor.
- **Cheap `CoordinationAccess.service`:** it no longer captures the route.
- **Agent log:** written by one batching writer thread.

**Remaining:**
- **In-process Core reads:** transcript pages, registry decoding, and private bus checkpoint verification. They compete for the GIL; the transcript slice moves them into the service.
- **Tab switch:** its own layout is about 2 ms; its 37–54 ms of wall time is mostly waiting behind those reads. Re-measure after the transcript slice; split the switch across frames if it still exceeds one.
- **GC:** 15 ms collections on the young generation.
- **Paint:** 5–16 ms screen updates when much is dirty.

## 2026-10-09: What "worst frame" measures

Under #openhcs load, the earlier worst frames (127–229 ms) were mostly not the app:
- **Snapshots:** the scenario's own screen snapshots run inside the app and take 105–220 ms each. They accounted for every event-loop lag over 50 ms in a loaded run. The meter now leaves out frames, lags and inputs that overlap a snapshot.
- **Tab build:** building a never-shown tab (about 68 widgets) takes about 200 ms before it can be painted. The loop stays responsive while it runs (lag ≤ 35 ms). That is tab-open latency, not a frozen UI.

The meter now reports three measures:
- **Frame work:** busy time between paints.
- **Busy stretch:** the longest run of callbacks with no paint.
- **Event-loop lag:** how long an input or a paint would have waited, probed every 4 ms.

Lag is what a person feels as jank. Tab-open latency is measured separately, by tracing the tab activation.

**After this change, under load:**

| Measure | Value |
|---|---|
| Worst lag | 34.7 ms |
| Lags over 16 / 33 / 50 ms | 18 / 2 / 0 |
| Lag p99 | 6 ms |
| Input-to-paint p95 | 13 ms |
| Cold tab build | 211 ms |

**Remaining lag owners:**
- tab close, `close_many`: 35 ms;
- tab click, `SessionLabel`: 19 ms;
- mode switch: 10–14 ms;
- footer rebuild: 18 ms;
- paint with much dirty: 10–22 ms;
- `SessionObservation._run`: 13 ms;
- `Conversation` messages: up to 19 ms.
