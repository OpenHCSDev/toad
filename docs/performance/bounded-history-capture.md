# Root-only history/frame observation

This is an observation tool, not a history performance repair. Authors do not run it. Root reviews the exact head, selects the private-process controls below, and only then attaches to the current frontend. No synthetic app, UI input, screenshots, provider calls, saved-history decoding or service operations are involved.

## Owners and first split

`frame_meter.BoundedCapture` owns admission, encoded record bytes, weak labels, timers, hook restoration and atomic publication. Both public entrypoints accept `max_records`, `max_bytes`, `metadata_only` and return its idempotent bound `finish` method. `MethodTarget` owns descriptor preservation and inherited-declaration restoration. Metadata adapters register their target at subclass declaration; there is no separate target roster in the launcher.

The source declarations used are:

- `PreparedPageSource.get`: source/scope, request end/cursor; the result is the actual `PreparedTranscriptPage` passed to row preparation.
- `PreparedTranscriptPage.prepare_rows`: the same weak page label, cursors, fragment count, actual selected-category identity, direction, target width, requested rows and returned rows.
- `LineHistory._load_page`: inclusive parent span, history/source/scope/filter identity and width. `needs_more` is its boolean return, **not** proof of publication.
- `LineHistory._extend_and_trim`: actual staged page label and local/source growth. `TranscriptSourcePreparation.rows_published` joins through that history and `_load_page` parent. A row-admission event is not completed layout.
- `ToadApp.select_session` / `_switch_mode_ready`, `SwitchToast.show`: natural tab request/switch and toast duration, never title/body serialization.
- `FramePresentation.written` and `_FlushSignal.deliver`: UI acknowledgement versus writer-thread flush signal. Neither is pixels.
- Frame/input/layout hooks remain in `install`. A frame sample requires an actual successful `LinuxDriver.write` directly from the declared `App._display` code. Merely entering `_display`, headless publication, a batch-gated call, or begin/end-update control writes cannot create a sample.

Labels are local to each output, use monotonically assigned integers and weak references, and emit identity/retirement records. No product object is retained or hashed. Unsupported weak lifetimes are `null`, not bare reusable `id()` values. Cross-file correlation uses the common monotonic clock, not coincident label integers. `ValueMetadata`, declared once at the lazy observation boundary, uses the existing `MroProjection`/`handles` mechanism. Native `TranscriptPage`/`TranscriptCursor` retain native byte offset, assigned wire sequence and selected witness scalars. `WirePage`/`WireCut` use their actual `source`/`cursor` declarations; `PageCursor` supplies lower/upper/history-source capabilities, including live, historical and unread cuts. `PreparedWirePage` inherits the shared prepared-page handler. `MessagePage` contributes selected evidence type, message count and derived endpoint cursors, never message bodies. Missing values are explicit absent records; other unsupported classes emit a bounded type/unsupported record instead of probing native fields or stopping the capture. Snapshot identity is a weak label, not a serialized `TranscriptReadIdentity`.

Parent spans are inclusive. Awaited thread CPU includes other work on that thread during suspension; it is not exclusive task CPU. Never add nested/concurrent durations. A first later display is a temporal candidate, not evidence that the same page geometry was painted. This first split can identify a dominant inclusive term; it cannot prove pixels, exact child cost, lock wait, ready-hit/eviction or a usable-page deadline. Missing page match, no older edge, zero frames or exhausted caps means inconclusive attribution, not success.

## Bounds and lifecycle, from the source (not executed proof)

1. Each record is JSON-encoded once using compact separators and UTF-8 before admission. Retained buffers contain only those bytes. No mutable nested product records are admitted. Metadata records have a fixed scalar shape, bounded names/paths, and no event/message/fragment bodies.
2. `used` starts with the exact static envelope and every stream's key/brackets/separators. Each admitted record charges its encoded length plus its actual comma. Admission requires `used + incoming + FINAL_RESERVE <= max_bytes` and count below `max_records`. A cap stops admission immediately, even when restoration must await the UI loop.
3. `FINAL_RESERVE` is 8192 bytes for status/key/separators. Status fields are bounded strings, scalar clocks/counts and booleans; output byte count includes its own decimal spelling via fixed-point accounting. Hooks are already restored before writing. Output streams directly to one exclusive `.partial` and is renamed; no second bulk output is made.
4. Exact count/cap/error/censored-open-span/censored-input status is retained. Work occurring after close is unobserved, not falsely counted as zero drops. No record is appended by a late async completion. Async wrappers still return/cancel/raise through the original function.
5. All descriptors, target existence and running loop are checked before patching. Each installed hook remembers the original descriptor and whether it was inherited. Reverse restoration only replaces this capture's exact wrapper; a later wrapper is left alone and reported as superseded. Timer, explicit finish, admission error, cap and partial setup use the same owner.
6. Metadata collection does not start a stall watcher, install a GC callback, call `gc.get_objects`, traverse a heap, inspect coroutine locals, walk arbitrary dataclasses, or call `_subject`, `_field`, `_result` or product `repr`. Old standalone heap diagnostic functions remain explicit opt-ins; this launcher never invokes them.
7. Legacy `trace_calls(metadata_only=False)` retains its six-column JSON array. Metadata mode uses a `calls/events/pauses/capture` envelope. Existing frame/input/lag array shapes and `summarize` remain; immutable input-handler completions are coalesced by arrival using the last observed handler end. Intrusive stack/heap diagnostics are no longer part of `install`; flat bounded events replace those unbounded maps.
8. `measuring_pause` borrows each active capped lifetime. Start markers, closed interval pairs and open interval IDs share its record/byte limits; there is no uncapped global interval list. Finish retains the earliest open/censored start and the admission-end clock in the reserved scalar footer: all unfinished exclusions overlap that end, so one union interval suffices. Nested intervals are bounded by admitted starts; late ends cannot alter a sealed capture. `summarize` preserves the complete capture status, excludes closed/censored pauses (including input-to-handoff crossings), and reports absent switch samples or historical missing exclusions as `unobserved`, not zero.
9. `BoundedCapture.complete_span` holds the existing `RLock` across accepting check, terminal admission, open-span retirement and censorship. Metadata errors and cap exhaustion remain inside that same transaction. Entry also checks admission under this lock; a wrapper losing the race with finish does not allocate an observed span. Finish cannot see a terminal record while still counting that same span as open.

## Root launch and recovery

Use the reviewed `tools/performance/capture_history.py` with the explicit current frontend PID, boot ID, `/proc/PID/stat` start ticks, canonical installed runtime directory and exact approved meter SHA256. The launcher checks the meter AST interface/hash and process birth/mapped runtime before any attach; unsupported contract fails before `sys.remote_exec`.

```
python tools/performance/capture_history.py start --approved \
  --pid CURRENT_PID --boot CURRENT_BOOT --start-ticks CURRENT_TICKS \
  --runtime /absolute/canonical/runtime \
  --meter /reviewed/checkout/tools/performance/frame_meter.py --sha256 APPROVED_SHA256 \
  --output /home/ts/.cache/agent-scratch/ROOT_OWNER/p903-UNIQUE
```

The controller writes immutable requests and copies `history_capture_remote.py` as `start.py` and **`cleanup.py`** in that run directory. Only copies with an adjacent request execute remote work; ordinary import of the publisher/identity helpers performs no attachment. Root must preserve that recovery script after uncertainty. The controller attempts start once, never replays it, and bounds each remote-exec helper to five seconds. Its 28-second observation deadline leaves up to seven seconds for a distinct cleanup operation and receipt, within a 35-second controller budget. Polling is local bounded completion metadata every 250ms, not agent polling.

The target rechecks birth/runtime, all loaded Toad/Textual/Core module locations, the meter hash and actual descriptors before patching. Controller and target use the same size-bounded source reader (256KiB plus one overflow byte). The target compiles and executes exactly that verified buffer with its registered module namespace and `__file__`; neither loader reread nor cached bytecode can replace the approved bytes. Metadata declarations are resolved before the first patch and included in the subsequent provenance check. Module filenames prove location, **not a hash of already-loaded code**. Missing/mixed runtime provenance fails closed. No particular conversation is required to obtain global frames; source mismatch and absence of an older page remain visible/inconclusive.

Both collectors request 25 seconds and 20,000 records each: calls at most 12MiB, frames at most 3MiB. Two code copies, two bounded requests and all bounded receipts reserve less than 1MiB, so partial/final output and metadata fit the 16MiB run bound. Captures may stop sooner at a cap. The owner reports actual interval/count; do not manufacture p99.9 from 25 seconds.

For a separate explicitly authorized recovery after inspection:

```
python tools/performance/capture_history.py cleanup --approved --output SAME_RUN_DIRECTORY
```

Do not retry a start or kill the frontend. A blocked/uninterruptible target may not execute either the duration timer or remote cleanup. `CLEANUP_UNCONFIRMED` is a real possible result; keeping a recovery script is not proof hooks were restored. A missing token does not prove an uncertain attach had no effect. Read each capture's `cleanup`, failed/superseded hook counts and cap/error fields, not just a group `FINISHED` label.

## Required private-process controls — UNRUN, root-owned

Project rules prohibit authoring/running automated tests here. These are the precise controls root must implement/select in its existing combined execution; they are not passing test claims:

- Real private event loop, actual `BoundedCapture`, fresh persistent output: Unicode scalar records at the exact comma/envelope boundary; assert final stat size equals `capture.output_bytes` and never exceeds byte cap. Repeat with count cap, oversize first record, no records and recording-encoding error. Include the final/error record and intermediate `.partial` size.
- Resolve valid sync, coroutine, inherited, classmethod and staticmethod declarations plus one invalid/missing/property target. Invalid descriptor/loop validation must occur before any assignment. Arrange a real partial-assignment failure in private control classes; assert reverse restoration and a bounded setup-error receipt.
- Start/finish/timer-finish twice; finish an async call before/after expiry and after cancellation. Assert descriptor binding, original return/exception/cancellation behavior, no late record resurrection, no retained product objects, timer cancellation, open-span censorship and identity retirement/reused-id distinction.
- Put a later wrapper over this capture and finish it; later wrapper remains installed and supersession is reported. A pre-existing capture must not be overwritten. Restore inherited declarations by deleting the owned override, not copying the inherited method onto the child.
- Run the exact remote entry/copy protocol on one private process with a real event loop, no Textual app: unsupported contract/provenance must fail before patching. For successful setup root can use its private real frontend path. Exercise setup failure after the first returned handle, INT/TERM controller cleanup and late completion. Never replace production owner algorithms with mocks.
- Check legacy trace array and frame summary callers, zero-display runs, multiple handlers for one input, and that no headless/batched/no-payload display creates a sample. Confirm live metadata paths cannot reach representation/heap/stall helpers.

### Four source-review counterexamples — root's additional UNRUN selection

- Drive the actual observation decoder with native prepared pages/cursors and wire prepared pages, `WirePage.unread`, live/historical/before/after cuts and unknown objects. Confirm the decoder uses only declared fields, emits explicit absent/unsupported evidence, and unrelated call/frame admission continues. Verify weak-label limitations remain visible rather than replaced by bare IDs.
- On the real private loop, nest `measuring_pause`, close normally, finish inside an open pause, and exhaust each cap before a pause closes. Verify closed pairs are bounded, the censored union clips at admission end, late ends do nothing, all counts/cleanup/errors survive summary, and missing switch data says `unobserved`. Cover the first frame and input-to-handoff intervals crossing exclusions, plus historical summaries with and without actual pause/switch arrays.
- Retain the verified source buffer, mutate the backing path and place conflicting bytecode beside it before module execution. Verify only those retained bytes execute, with correct `__file__`, `__name__` and `sys.modules` registration. Oversize and hash mismatch fail before any patch. Exercise this through the real copied remote protocol; do not replace a product algorithm.
- Let a real writer-thread span complete while the owner loop attempts finish. Both return/error/cancel and cap-exhaustion cases must admit/retire atomically: no admitted terminal record also counted censored, no negative open count, and no post-finish entry/completion resurrection. Include an actual async suspension and later-wrapper restoration.

Root reported five private UTF-8/cap/oversize/empty/error-idempotence controls passing on parent `96a4e0d3cb561fe2efcca6b3905d08adeb20ae5d`. That is historical evidence, not qualification of this correction. No private process, product/meter import, test, capture or GUI operation was run by the author. Root still owes the combined controls and actual installed-window measurement; no speedup or dominant delay is established by this implementation.
