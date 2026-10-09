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
