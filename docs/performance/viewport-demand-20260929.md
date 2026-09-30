# Adaptive viewport preparation

Owner: TC2 continuation, PR214. Integration owner: Heisenberg, PR213.

## Ownership and implementation

DirectionalPreparation measures actual scroll velocity/direction and body delivery latency. DocumentViewport admits visible bodies first, then bounded directional batches through the existing shared PreparationRuntime/renderer/cache. Continuous samples update the same owned moving demand; reversal and idle replace it and drop stale batches. This avoids cancelling every admitted batch on each held-key sample. No second cursor, source, semantic state, pool or cache.

Larger default lookahead is configured at PresentationBudget: four reserve batches, 0.3 seconds prediction horizon, 0.2 seconds input idle deadline. All remain constructor parameters. The viewport bounds predicted distance to its height times reserve batches; item, widget, byte and pending-work limits remain with their existing owners. Faster scrolling prepares farther ahead; stationary demand returns to base admission.

Local page lookahead also prepares unmounted neighboring leaves from the existing immutable source/admission, so lazy PageDown does not wait for widget construction to begin pure work. The actual source page range and existing preparation intent fence this work; no second cursor or pending range exists. End skips this adjacency work.

Body lookahead now warms both grammar and highlighted code rows using the same MarkdownSyntaxRenderTask/TokenRenderTask consumed by foreground restoration. TranscriptFragmentView uses the typed transcript MRO consumer for stored text bodies. Prepared data belongs only to the existing bounded cache. Native widget construction/compositor painting remain native and bounded, rather than copied into another view.

End requests destination-only admission. A request during an admitted source operation belongs to that WorkingTranscript as a typed pending viewport resource. Completion hands it off only if the actual window reader revision still matches. Retirement unwraps and retires the source so parking cannot resurrect a cancelled WorkingTranscript. The replaced history-level loading/advancing/latest-revision flags and unused prefetched-edge record are deleted, including consumers.

## Verification and limits

Actual installed Toad/Textual viewport pressure journey passed: repeated PageDown, reverse movement, End, cold tail paint, draft/undo, idle shrinking, pending work zero; measured idle CPU 0.04 seconds in a 0.3-second interval, RSS 143646720 bytes and prepared bytes 112969. This small installed UI fixture is not native video acceptance.

Actual installed source history journey passed through all 105 records and End during a deliberately held edge read, with bounded DOM, final source paint and bottom position. First candidate on Core ab339 failed startup because integrated #210 requires SessionLoadAdmission; paired own candidate Core426 ec636 fixes that dependency. The next run caught a nonexistent destination admission call introduced by this worker; deleted it and reused the page's actual mount/compose. Failures are retained in owned scratch. An earlier teardown emitted an unawaited preparation coroutine warning; the existing worker now receives its coroutine function rather than a prematurely created coroutine. Actual parked-operation/queued-End resume and full source history checks subsequently passed without that warning.

Primary past-end-void reproduction is repeated/held PageDown at a not fully prepared bottom while lazy admission is ongoing, then reverse and idle. End is separate coverage; it does not prove the PageDown case. Heisenberg's #213 reader/follow/extent correction is now merged in main 4c20f882 after the actual installed 351-frame primary PageDown/reverse/return journey. This does not establish #214 native video acceptance.

Continuous installed saved-native acceptance pending: isolated Xvfb/st held PageUp/PageDown/reverse PageUp/End/idle; same-run profiler/action/kernel CPU correlation and short unprofiled comparison. Recorder sampling policy is now explicit and recorded; consistent reads default to avoid unverified nonblocking stack consistency. No assumption that profiler exit, source tests or counters prove a frame passed. No final 50 ms or global activation claim.

## Pair and resources

Own noneditable wheel uses merged Core426 d306d0df04e82af1084aa0d25aaa1484b693b0f2, Textual412 and the parent-verified native4ab package. Current main #210 6e56770 is integrated with its original process load witness and FailedSessionLoadAdmission contract; no older load fallback. Parent owns reviewed default activation. Current main 4c20f882, including the merged #213 reader geometry correction and #210 original load witness, is normally integrated. This main merge changes evidence and the accepted journey driver; production source and #214 recording tools are unchanged. Native fixtures are serial: urgent recovery/rename/deadline fixes precede this capture; source and provider-free UI work continue independently.

Persistent WT /home/ts/wt/toad-viewport-demand-20260929; owned disposable artifacts /home/ts/.cache/agent-scratch/toad-viewport-demand-20260929. No global package, live user root or another worker's source was changed.

## Checkpoint measurement

At 9703ea21 against normally integrated main 6e56770, the combined production checkpoint changes 11 files: **91 lines deleted, 267 added**. This includes the inherited #213 reader checkpoint; no claim that all are adaptive-scroll edits. Typed demand replaces the older velocity decay/nullable destination combination, and prepare_scroll replaces every _warm_pages caller. No hidden follow/status/source copy was introduced.

Census: no added type identity checks, long boolean chains/terms, codec subclasses, foreign absence probes, string dispatch/type switches, getattr defaults or attribute-by-name; None identity checks decrease by two. The one added string-key subscript replaces .get on the official SDK's guaranteed LoadSessionRequest field_meta declaration, at the same boundary, rather than restating any wire shape. History/reader geometry correction landed in #213; queue/turn/start ownership to #211/Core425; complete native footage/profile assessment is still pending.

## First native recording counterevidence

Candidate cd3b57dd captured the actual saved-native installation through isolated st/Xvfb held PageUp, held PageDown, reverse, End and idle. The physical focus screenshot confirms the message area, and the 40-frame PageDown sheet moves through saved blocks 0 to 31. End reaches SOURCE END. These reviewed frames show no blank extent, but pending lazy-read geometry was not measured; #217 retains primary growing-end closure.

Consistent py-spy produced **674 samples, zero reported errors**. Kernel UI CPU: PageDown 3.22 seconds in 4.785 seconds (67.3% of one core), idle 1.14 in 4.812 (23.7%). Pure render workers used approximately 0.01 seconds during idle. Sampled wall stacks include notification selection, table/codec reads and sidebar route observation; this identifies an investigation lead, not proof of redundant work or exact CPU attribution. The parent received this out-of-scope observation.

**Whole journey failed:** the 100-second controller expired during postcapture slow-clip encoding. The native fixture sent one controlled request with zero provider errors; the post-recording message was never sent. Recorder and controller cleanup report no remaining owned processes or errors. Raw footage/profile remain in the owned persistent scratch directory; selected failure, CPU and physical frame evidence is committed under evidence/viewport-demand/native-profiled-cd3. No READY or global live claim.

Reading the shared MroDispatch contract then caught another concrete defect: every handler is awaited, but TranscriptBodyPreparation's base handler returned synchronously. It is now async, and the actual decoded saved-source/render journey exercises that contract. The obsolete mounted prefetch test patched out production edge checking and referenced the deleted _prefetched_edges field; 67 deleted lines remove that patched UI path, its dead field consumer and unused waiter and it reuses the actual installed source-history journey instead. No replacement UI or protocol mock.

The corrected async-handler candidate passed the actual installed 105-record history journey, shared source-body rendering, held-edge End, tail paint and bounded DOM. This focused pass does not replace the pending whole saved-native capture/post-message journey.

## Current integration and capture boundary

Current main #211 3b019be0 is normally merged without source conflicts. The owned pair now pins merged Core425 b554c1e37373c29a578341f543018af92df3e800 with the same verified native4ab/Textual412. The native driver derives readiness from the canonical turn owner and submission queue rather than the removed view-level queue mirror.

Mendel explicitly accepted the disjoint recorder postprocessing claim. Declared ReviewTiming cases own inline versus deferred encoding; the native driver requests deferred review. The existing recorder captures raw footage, profile/action correlation and cleanup, then returns to the original native-owner input check. The separate --review-recording operation reuses the same artifact encoder after native retirement, preserves the original receipt and produces its own review receipt. Controller deadlines are unchanged. Historical failed cd3 footage is being encoded independently; this does not convert that failed native journey into a pass.

Offline review completed with zero cleanup errors: all six 8× clips and contact sheets were generated from the same raw capture. The historical capture receipt remains failed; review completion is not native input acceptance. At the normally merged #211 checkpoint 4169de69, the current production difference from main 3b019be0 is **72 deleted / 250 added lines in eight files**. The async-body correction contributes one replaced definition; the obsolete test path contributes 67 deleted lines. No global ownership scan or final performance claim.
