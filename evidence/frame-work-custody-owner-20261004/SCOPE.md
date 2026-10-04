# Frame work custody continuation

Continue full performance from scoped415/49 in the same checkout/holder.
415 original140.726s preserves16warm/7input/37 bodies; motion is stepped,
Up worst192.11ms, markerUI71.69%. No CPU/smoothness/144Hz gain. No repeat.

Source finding: FramePresentation.callbacks owns pending work and writer release,
but PresentedFrame.defer bypasses it via owner.call_after_refresh(callback).
Every newly mounted viewport body therefore schedules the same window request
again; retirement batches and restored cohorts use that bypass too. Shared chrome,
sidebar read/navigation and session hydration consumers use the same frame API.

Use the existing FramePresentation callback resource for every state; release each
owned callback once at its original after-refresh or written-frame boundary.
Keep delayed work through a changed pending/suspended scene; closing revokes it.
No new queue/timer/flag/type, no native/source/history/provider changes. Existing
state hooks still select when release is legal; consumer policies remain theirs.
AST288 Toad/249 native modules, zero parse omissions; all defer owners and callback
writes read. Dynamic callback/alias resolution not proved. This closes IMPL-12
shared lifecycle bypass; profile shows frame/layout activation, not CPU dominance.

Batch source implementation first; then existing actual App frame/geometry sanity
and one affected installed saved-history workflow when changed source is coherent.
No test-first design. Frame dedup is not a speed or smoothness claim before evidence.
Personally inspect original moving frames during the next needed recording.

Full scope remains ACTIVE: CPU/raster/cold/firstpaint/warm A/B/A/boundedrunway,
velocity/reversal/growingEnd/void, input/focus/draft/Undo/TC1T9T4, IRC/DM/busy,
sidebar/tab/compaction, uninterrupted motion and configurable144Hz6.944ms target.
Kepler owns native Compositor/Widget; Heisenberg owns this Toad frame family.

## Published implementation checkpoint

Production bc6decd00f867e90cf7b78690015ac8b4672c1d8: original FramePresentation
now admits each owner/callback once. PresentedFrame joins its existing callback
resource and after-refresh requests the same release method used by actual writer
completion. That method checks original frame readiness, removes the resource
once and sends work through the original message pump. Pending/suspended scene
work remains queued; closing clears it. Deleted direct PresentedFrame publication
and the separate present() callback-clear/invoke implementation. All11 original
production defer consumers inherit this change without local queues or guards.
One production file11 deleted/22 added; no native/capture/provider edit.

AST after288 Toad modules/zero omissions; owner-before also249 native/zero
omissions. Source WIP, not Ready: no changed installed App/film qualification yet.
415/49 source/film remains frozen and can ship independently. Next batch prevents
duplicate viewport admission scheduling and stale scene callback release through
the real App's frame lifetime; the next changed saved-history journey measures
actual consequences. No speed/dominance claim from this source correction.
