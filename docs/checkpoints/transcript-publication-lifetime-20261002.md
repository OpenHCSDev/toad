# Original transcript application lifetime

Owner: Schrodinger. Source baseline: Toad 2f4effb6, Core29248,
Textual559547, native5184. Separate from qualified Core499/501 native work.

## Actual defect

Canonical compaction501 fork A return crashed at 00:21:21 with WorkerFailed:
`StaleRevision('Transcript application retired before source capture')`.
The same original native attempt subsequently committed and answered. Preserve
bc86 reservation, c6c11 commit, original input and all failed capture artifacts.
No replay, cancellation, provider call or public activation is part of this fix.

## Semantic closure before validation

Read the existing TranscriptPublication ancestor, concrete source/snapshot/
checkpoint members, SourcePublicationRequests, TranscriptPresentation restore/
suspend, WorkingTranscript and their callers. The original application epoch
and resource cohort own publication eligibility; backend source revision is a
different fact. Collapse independent rejection handling into the existing
publication family, delete bypasses and preserve accepted retirement joining.
Do not add another epoch/seen registry, source mirror, query guard, per-site
catch or reinterpret invalidation as successful publication.

Patterns: IMPL-12/IMPL-13 (drifting execution paths), IDEN-1 (application
retirement represented as backend source revision failure).

Heisenberg retains viewport/budget/history edge methods. Mendel owns
HandlingPublication reference projection and historical notification methods.
Arendt owns native turn/custody. Those semantic claims are not changed here.

## Final validation

After coherent source closure, batch affected family checks. Use the already
completed canonical501 saved source through the real installed ACP/Toad path
for A/B/A and source refresh; no new input, compaction or original replay.
Record original source/resource/generation and actual retirement disposition,
with source byte provenance. Native499 qualification is independent of this
UI acceptance. Do not claim full warm rendering or latency improvement.
