# Wire row publication lifetime

Working source checkpoint only. No installed acceptance, timing improvement,
physical motion or CPU claim. Continues the full UI performance scope after
accepted #430; its original qualification remains unchanged.

## Existing owners and deleted work

MountedMessageHistory owns the bounded wire rows and source reader. HistoryWindow
owns native mutation locking, interaction/reader protection, compensation and
paint admission. Source admission and native publication are different lifetimes.

Receipt and tail replacement previously removed native rows before _mount_page
entered reader protection. Style replacement instead held a global App batch
across native removal and mounting. One native_publication context now borrows
HistoryWindow's existing source lock and native reader fence around the complete
row mutation. Page, receipt, tail and style consumers use it. All five _mount_page
calls borrow the already-selected protected cohort; its second reader acquisition
and cohort decision are deleted. The style-only global App batch is deleted.

HistoryWindow.preserve_history releases its native lock before reader compensation
awaits layout. Nesting it around the old _mount_page fence would hold that same
lock while waiting for layout, which WorkspaceScreen refuses during mutation.
The context migration removes that nesting rather than introducing a reentrant
source lock or a second reader anchor.

HistoryWindow.preserve_reader now borrows the existing native geometry revision
for this context's lifetime. An unchanged page/already-live resource does not
request and await an invented reflow. Native mutation still requests layout,
then uses the original anchor/compensation event and animation translation.
No persistent revision, cache, flag, timer or queue is added.

## Whole consumer source evidence

owner-before.json and owner-after.json use existing refactor-audit Package and
Repository. All 288 Toad and 249 frozen Native59 modules parsed with zero omissions.
Named AST declarations/attributes/calls are evidence, not dynamic dispatch proof;
unrelated names and external aliases are not claimed resolved.

## Remaining closure before final validation

CommsScreen still awaits toggle_style on its message pump. The next source pass
must admit this native work on the original history worker lifetime, preserve each
style request through source work/retirement and handle a cancelled partial row
publication coherently. The new outer context also captures protection for an
unchanged source read; its actual mutation-demand ownership needs adjudication.

Final affected installed App validation follows this coherent source closure and
a fresh actual holder purpose. There is no package/import/execution lease now.
No old #430 App, movie, provider or saved input is repeated for this checkpoint.
