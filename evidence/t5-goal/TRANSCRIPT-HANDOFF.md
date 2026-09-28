# Transcript publication lifecycle

Replaced TranscriptHistory's `_committed` field and its commit/attachment/closing/pruning chains with TranscriptState members using core LifecycleState and DeclaredFamily. The source state owns accepted/provisional coverage; observed Detached/Pruning/Closing states retain that source identity and deny publication. Shared implementation is inherited by suspended states.

Textual sets prune/closing facts synchronously before its queued Prune/Unmount messages, including ancestor removal. The one framework adapter in transcript_state.py observes those actual Textual fields; TranscriptHistory neither stores nor recombines them. Using only on_unmount would permit late pages during this interval. No copied framework flags or parallel lifecycle store is introduced. Domain coverage persists while the source is being removed, preserving the prior source-retirement contract.

Fresh installed-wheel receipts:
- transcript-paging.txt: first-to-last and return paging, bounded DOM and adjacent cursors pass with actual session-file reads.
- transcript-checkpoint.txt: 432 committed live blocks retired, peak3 outer widgets, stable viewport/selection/identities/source access pass.
- transcript-teardown.txt: actual Window removal discards the outstanding page.
- transcript-lifecycle.txt: real source file, provisional mount, accepted commit, synchronous remove-before-Prune admission denial and detached final state pass; guard finds no `_committed`, `_closing`, `_pruning` references in TranscriptHistory.

New source declaration owner85 lines; widget11 added/6 deleted. The state members and single framework boundary account for net additions. New62-line mounted lifecycle/deletion test covers the specific removal race rather than duplicating every state combination. No persistent store changes, live mutation, provider calls or CI wait.

Remaining T5 transcript scope: filter overlay state component and transcript event-owned merging. This checkpoint proves publication lifecycle only; full T5 is not marked complete.
