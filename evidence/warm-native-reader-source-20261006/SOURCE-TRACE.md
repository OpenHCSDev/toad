# Original warm03 native reader trace

Determining Toad source: d0dcde2714bee906a33fa7261a5cb7103f0e5311.
Installed product source remains the frozen 476 union; no package is changed.
Original warm03 is consumed and independently closed. Its raw failure, two
journals and 65 fixture files remain held unchanged.

## Original result and limit

The original 36.296851687 second App failed at
`ReaderCheckpoint.capture`: no visible `MarkdownBlock` descendants overlapped
the window's scrollable content region. Source coverage, displayed cursor,
strict registered history, draft/undo setup and non-tail scrolling had already
been reached. No warm return or eviction return was verified.

There is no retained body geometry/paint snapshot at this exact assertion.
The failure does not establish that the native reader was blank or which body
measurement state was present. No later runtime is used to invent that evidence.

## Source and selected attachment

1. `thread_navigation_installed_journey.prepare(long_history=True)` uses the
   existing real CommsClient load/prompt path. Exactly two original localhost
   requests create alpha/beta journals with sixteen user paragraphs each.
   The original saved snapshot includes context, user text and native response.
   Neither a synthetic transcript nor a reconstructed native tree is inserted.
2. `ThreadTarget.open` delegates to original thread navigation and declared
   session admission. `WorkspaceSessions.select` retires the departing source,
   admits `LoadingWorkspaceSource`, mounts the destination's own native tree,
   then publishes `ShownWorkspaceSource`. `NativeSessionSurface` retains or
   evicts the original `OperationalSessionPresentation`; it never changes the
   native source's session identity to provide a reader witness.
3. `ConversationCommsConsumer.transcript_snapshot` calls the conversation's
   `TranscriptWindow.snapshot`. `SnapshotPublication` joins the original
   conversation pump, validates the actual attachment/source frontier,
   prepares `TranscriptRenderTask`, mounts `TranscriptHistory`, publishes its
   committed source and retires only covered original presentations.
   `painted` updates the displayed cursor at the actual refresh callback.
   Source coverage and this cursor do not certify a particular rendered leaf.
4. `TranscriptHistory` owns original pages, admissions, fragment views,
   committed cursors and source workers. Parking removes its source-work
   membership; resumption restores the same source and reads its current cut.
   `TranscriptPageView` bounds real fragment admission and extends the actual
   native tree under the original reader/history lifetime.
5. `TranscriptFragmentConsumer` splits real user/Markdown source at Markdown
   block boundaries. `TranscriptFragmentView.compose` uses the existing
   `TranscriptBlockConsumer`: user events become `UserInput`, whose own compose
   **does include** `PreparedConversationMarkdown`; assistant text becomes the
   ordinary agent response. A user paragraph is not a non-Markdown substitute.

## Native output has an existing retained-paint lifetime

`TranscriptFragmentView` and `PreparedConversationMarkdown` both compose
`MeasuredViewportBody`. The window's `DocumentViewport` registers the outermost
body boundary, derives required/ahead membership from committed native geometry,
and uses the original `PresentationBudget.admit` with actual source and paint
costs. It restores an admitted dormant body only when `body_ready` is false.

`LiveBody` renders the ordinary descendant tree. Original retirement captures
the native subtree with Textual's `render_subtree_strips` (the same arrangement,
line and chop implementation), retains its `PreparedRichContent` in
`RenderedBody`, publishes that resource, and then removes reconstructible
children. `RenderedBody.ready` checks its original paint/style/native lifetime;
`RenderedBody.render` crops those same captured strips. The measured body is
then the native `_render_widget` and is not a container in the compositor.

Thus a ready retained fragment can reenter the actual visible viewport and
paint its original user/assistant rows while **no descendant MarkdownBlock
exists**. `DocumentViewport._reconcile` intentionally preserves that valid
paint instead of recreating the subtree. Scroll and a successful refresh do
not require `RenderedBody` to become `LiveBody`; interaction owns that
materialization when needed.

## Checkpoint consumer discrepancy

The existing checkpoint sees only visible `PreparedConversationMarkdown`
descendants and stores `MarkdownBlock._render_cache`. Its capture and verify
both omit the original `RenderedBody.content` native resource. This is a
source-supported counterexample to the checkpoint's assumption, not proof
that this state caused the original warm03 failure.

The coherent consumer correction is to retain exact resources for both
existing native output forms: live Markdown blocks and ready visible rendered
text fragments. The latter must be original committed user/Markdown fragments,
overlap the actual content region and native clip, and emit nonwhite original
cropped strips. A retained extent, a loading label, context disclosure or an
empty source cannot supply this witness. Verification must keep exact body and
paint-resource identity, the complete committed page/fragment identity,
editor Document/Undo, reader position, composited paint and unchanged raw page
read count. Failure diagnostics must describe the actual owner/resource state
before the strict assertion; they cannot manufacture success.

No production paint correction is justified by the original evidence. No
force focus, reconstruction, timer, budget change, renderer substitution or
global change to generic `settled` belongs in this correction.

## Remaining acceptance

The existing warm-only journey still requires a real departure/return with
exact warm identity and raw reads zero, followed by genuine original-owner
eviction and Document/Undo/non-tail restoration. Both original failed branches
remain zero. Any changed installed qualification requires a fresh specific
purpose and matching original source proof/READ/EXEC; this source work grants
none. Loaded 4/16/32/64 and configured continuous >=40 MB remain separate,
unfinished obligations.
