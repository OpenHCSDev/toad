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

Primary past-end-void reproduction is repeated/held PageDown at a not fully prepared bottom while lazy admission is ongoing, then reverse and idle. End is separate coverage; it does not prove the PageDown case. Heisenberg owns reader/follow/extent correction and the remaining known reader jump in #213.

Continuous installed saved-native acceptance pending: isolated Xvfb/st held PageUp/PageDown/reverse PageUp/End/idle; same-run profiler/action/kernel CPU correlation and short unprofiled comparison. Recorder sampling policy is now explicit and recorded; consistent reads default to avoid unverified nonblocking stack consistency. No assumption that profiler exit, source tests or counters prove a frame passed. No final 50 ms or global activation claim.

## Pair and resources

Own noneditable wheel uses merged Core426 d306d0df04e82af1084aa0d25aaa1484b693b0f2, Textual412 and the parent-verified native4ab package. Current main #210 6e56770 is integrated with its original process load witness and FailedSessionLoadAdmission contract; no older load fallback. Parent owns reviewed default activation. Normal #213 reader geometry checkpoint 65b5ee23 is integrated. Native fixtures are serial: urgent recovery/rename/deadline fixes precede this capture; source and provider-free UI work continue independently.

Persistent WT /home/ts/wt/toad-viewport-demand-20260929; owned disposable artifacts /home/ts/.cache/agent-scratch/toad-viewport-demand-20260929. No global package, live user root or another worker's source was changed.
