# Wire row publication lifetime

Working source checkpoint only. No installed acceptance, timing improvement,
physical motion or CPU claim. Continues the full UI performance scope after
accepted #430; its original qualification remains unchanged.

## Existing owners and deleted work

MountedMessageHistory owns bounded wire rows and the source reader. HistoryWindow
owns native locking, interaction/reader protection, compensation and frame
admission. CommsScreen owns the user's style action. Original node workers and
TranscriptSourcePreparation own asynchronous execution and source retirement.

Receipt/tail replacement previously removed rows before _mount_page entered the
reader fence. Style replacement used a global App batch across prune/mount and
CommsScreen awaited it on its own input pump. The original native writer now owns
complete row acquisition/commit/retirement for page, receipt, tail and style.
All six _mount_page calls carry their retained native association and original
style declaration. CommsChatView consumes that declaration when constructing
rows; it retains direction/membership display semantics.

New rows remain acquisition resources in AsyncExitStack until native mount
completes. An interrupted mount retires those resources before opening the fence;
original committed rows/style remain intact. Native commit updates row association,
order, style and edge metadata synchronously before pruning old scene resources.
Prune retires the old scene before its asynchronous completion. The original
AwaitRemove receipt is joined AFTER the Window paint/reader fence has closed;
already-retired old Unmount work does not block current-row paint. Only surviving
retained rows supply the reader anchor, so removed rows cannot be retained as
layout targets during that await. Cancellation at that later boundary retains the
already-committed new rows. A revoked source returns no commit receipt; it does not
advance page witnesses. Duplicate native
trimming loops were replaced by the same direction-selected existing row writer.

One native_publication context borrows the original Window reader/native fence
only when actual native rows change. Unchanged reads skip protection acquisition
and reader layout. The style-only global App batch is deleted. Read-error reset
also borrows this fence; its actual removal receipt and source reset precede the
completion await outside that fence.

HistoryWindow.preserve_history releases its native lock before reader compensation
awaits layout. The writer does not nest that fence. HistoryWindow.preserve_reader
borrows the original native geometry revision for its context: unchanged resources
do not manufacture a reflow; actual mutation retains the original compensated
layout event/animation translation. No persistent revision/cache/flag/queue added.

CommsScreen's style action now admits work on the original history node worker.
Each request acquires the original history source lock; it does not use exclusive
worker replacement or the pager's single source-work admission to drop a toggle.
Existing retirement cancels/joins that node's workers. Publication rechecks source
availability after mount before committing the acquired resources. Native global
Widget/App batch behavior is unchanged.

## Whole consumer source evidence

owner-before/after record the initial context checkpoint. family-before/after use
existing refactor-audit Package and Repository across the complete production and
original test roots, including message factory/Screen/row/native/reader consumers.
Named AST declarations/attributes/calls are evidence, not dynamic dispatch proof;
unrelated names and external aliases are not claimed resolved. Parse omissions
and counts are explicit in each record.

## Remaining affected validation

Required current-source Debt and one affected installed App remain. That App must
cover pending native row mount/removal, source retirement/cancellation, input and
resize while a style worker is pending, repeated style requests, source receipts,
page order/bounds, original read acknowledgement and whole shutdown. These claims
are not established by source or the prior #430 Tool/modal App.

There is no package/import/execution lease now. A fresh actual holder purpose and
archive precede installation. No old #430 App/movie/provider/saved input is repeated.
Full rapid-scroll/sidebar/thread-open/CPU/144Hz acceptance remains unfinished.
