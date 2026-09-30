# T5 source operation lifetime

Owner: inbound/source worker, continuing merged #207. Base: merged Toad
`533c7f6c`. Shared-file coordination: #202 owns compose, mount, retained admission
and unmount custody; this change owns page-load, checkpoint advancement and
initial projection admission. TC2 owns ACP event and model boundaries. The
integration owner owns backend turn, cancellation and input progress.

Current T5 witness: `TranscriptHistory` stores `_loading` and `_advancing`, then
recombines them at checkpoint admission, scroll-edge scheduling, paging, End and
projection admission. These represent source operations, not backend turn state
(IDEN-3, IMPL-10). Close their entire caller set through the existing
`TranscriptState` family: operation states own admission, completion and retirement.
An operation completing after source retirement must never restore publication.
Delete both flags and their consumer checks. Preserve original source revisions,
receipt frontier, durable chronology and the existing loader/preparation owners.

Acceptance: actual installed continuous saved-source application with edge paging,
End, filter projection, tab return, checkpoint advancement and source retirement;
the original installed inbound/switch/send journey remains the delivery check.
Use the existing controlled localhost provider and native/ACP infrastructure.
No live owner restart, prompt or package activation is performed by this worker.
This is a draft assignment receipt; no implementation or readiness is claimed yet.
