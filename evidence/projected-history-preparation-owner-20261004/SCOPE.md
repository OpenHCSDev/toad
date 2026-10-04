# Projected history preparation

## Working source checkpoint

This successor starts from frozen joined441442 head
`2a844fa34c2370fce4341e788fb4448f83467d1e`. Its source and evidence stay separate
from the accepted single installed441442 App. No holder purpose is open for
this successor.

## Owner and deleted work

`CategoryProjection.project` owns category membership. It replaces only the
prepared fragments and retains the original page, cursors and byte accounting.
`ProjectedTranscriptSource` owns the lifetime of that projection.

Previously `boundary` and foreground `get` projected pages, but both prefetch
branches yielded the upstream/raw fragments directly. The existing
`TranscriptHistory.prepare_scroll` consumer then prepared Markdown bodies
excluded by the active category projection. This is a source bypass, not a
measured CPU attribution.

The source now publishes boundary, foreground and both speculative paths
through its existing projection inside one `_project` operation. That operation
checks original source custody before and after asynchronous projection. Both
prefetch branches also recheck the original demand callback before yielding.
No consumer has to repeat category selection or source custody.

The raw reader still owns cursor advancement, transport rounds and runtime
capacity. Empty projected fragments retain the raw interval. Speculation does
not use the foreground empty-page scan and does not acquire extra pages to fill
an empty category projection. No map, cache, flag, timer, queue or native change
was added.

## Source coverage

`owner-before.json` uses the existing refactor-audit `Package` over all288 Toad,
394 test, 41 tool and249 native59 modules, with zero parse omissions. The relevant
relationships were read through `ProjectedTranscriptSource`,
`CategoryProjection`, `TranscriptPageBuffer`, `TranscriptHistory.prepare_scroll`
and `TranscriptBodyPreparation.prepare_fragments`.

This is the IMPL-4 ownership case: an existing implementation owns the operation
and its callers consume it. Lexical census does not establish dynamic external
aliases or overrides, runtime equivalence, installed UI behavior or duration.

## Remaining qualification

After the coherent source change, extend the existing prefetch control to cover
both raw/upstream branches, empty projected intervals, and source/demand
revocation while projection is pending. No broad old App, movie, build or
provider repeat is part of this checkpoint. Source-qualified and installed
qualification will be reported separately. Full runway and continuous workflow
performance remain unfinished.
