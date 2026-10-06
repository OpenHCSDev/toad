# Drive channel reads from the existing coordination observer

## Original owners and removed work

The actual live profile points to CommsChatView._refresh and root validation on the UI thread, with message_notifications and record decoding across executor threads. The channel separately scheduled _refresh every50ms, even when its source was unchanged. CoordinationAccess already owns one application route/revision observer and publishes CoordinationObserved. HistoryViews.revision includes registry, catalog, bus/history, activity/runtime, read ledger, goal waits, coordination database/WAL and the original activity expiry tick.

CommsChatView now consumes that original publication through its inherited command-source handler and existing MRO dispatch. The parent command update remains; the same consumer schedules the existing history worker and notification task. The competing per-channel timer/import is removed. SessionSelected refreshes the current retained channel; hidden channels retain the original early current-view refusal. Startup and committed-send refreshes remain at their existing owners.

MountedMessageHistory's original post-layout edge callback owns newly visible messages on scroll, resize and row publication. It now requests the existing painted-read and notification operations there, preserving source checkpoint and committed geometry checks. No new timer, queue, revision copy, persistent cache or retry manager is added. Original route/read/write fences and receipt decoding remain unchanged.

## Source and native App checks

Original audit.Package parsed288 source,401 test and40 tool modules with zero omissions. The source trace covered channel mount/selection/send, inherited CoordinationObserved handling and MRO override selection, the single application observer and complete WireRevision, pager edge/resume/publication and painted read receipt lifetime.

The real Toad App/HeadlessDriver check uses an original private initialized bus and three new authored records, without native agent/provider/public input. It instruments the actual HistoryViews.message_notifications entry using Python profiling, without replacing its behavior. A2.2-second idle sample made4 notification reads. A new bus record appeared in the current channel; a parked channel made zero notification reads and showed its new record on return, retaining its original view. Native compositor SVG text contains both updates. This screenshot re-renders the native compositor; it does not certify physical terminal publication or frame time.

Matched dependencies are original current Core697 source and corrected native73 checkpoint3e73a51ab. Raw logs and SVGs are retained under `/home/ts/.cache/agent-scratch/parent-comms-observation-20261006`. The first fixture omitted its normal project thread, producing an unregistered-command warning; that refusal is held. Its actual thread declaration corrected the fixture, and the final App check has empty stderr. An initial raw SVG string assertion failed on XML text encoding; decoding native SVG text entities fixed the check without any production change or weakening of visible text.

Public installation is unchanged. Small-source App observations do not establish simultaneous-agent frame latency, whole saved-history acceptance or provider/native qualification. Before/after original-source comparison and installed physical measurement remain separate steps.
