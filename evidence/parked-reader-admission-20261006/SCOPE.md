# Preserve parked reader page ranges

Warm04 verified two real warm returns with the original prepared/native content identities and zero page reads. A genuine presentation eviction then failed the unchanged reader offset assertion. Two localhost inputs completed without provider errors. The run and journals remain retained; the original packages were restored once and all private children joined. The whole return is at `/home/ts/wt/toad-warm-rendered-reader-20261006/.artifacts/warm-presentation-admission-source-20261006/485-current471-warm04-installed-purpose/whole-handback.json`.

## Source defect and correction

`NativeSessionSurface.retire` parks each pager through `TranscriptSourcePreparation.retire_source`. That method removes it from `HistoryWindow.histories`, the original active source-work set. Its mounted pages remain owned by the conversation. Later `OperationalSessionPresentation.evict` calls `SessionViewState.capture`, whose `ReaderPosition.capture` previously read only that emptied active set. Its offset retained no admitted source ranges. A rebuilt pager therefore used its default fragment range rather than the original range against which the offset was recorded.

`ReaderPosition.capture` now derives page admissions from the original native `TranscriptHistory` children whose declared window is the captured window. It includes parked pages and excludes a nested window's own pagers. `OffsetReaderPosition.prepare_history`, immutable `CommittedInterval`, `TranscriptPageView.restore_admission`, and preparation-before-mount carry the same original range to the replacement. No second membership store, reader cache, timing mechanism, policy or budget was added. The active source-work set, parking and frame gates are unchanged.

The existing warm acceptance now checks that its original checkpoint page admissions survive the genuine eviction capture. Exact warm body/page/content identities, raw reads, editor Document/Undo, CtrlZ/redo and reader offset assertions remain strict. Default geometry and authored Markdown consumers use the corrected capture without API changes.

## Verification and remaining work

Full original Package parsing: Toad 288 production, 400 test, 40 tool modules; pinned native Text 249; selected Core production parsed separately. Zero omissions. The two changed modules compile without application imports; only `ReaderPosition.capture` and `warm_admission_acceptance` change. No source tests or mounted run were repeated.

This source counterexample is concrete. It is not proof that it alone caused warm04's offset assertion. The corrected production is not byte equal to the existing paired Toad wheel, and no replacement wheel is built or claimed. Any affected mounted qualification needs a separately issued purpose and a truthful full source/root artifact. Configured continuous source preparation remains independent on `integration/configured-continuous-owner-20261006`; its paired operands are published and its floor/source witness remain unbound.
