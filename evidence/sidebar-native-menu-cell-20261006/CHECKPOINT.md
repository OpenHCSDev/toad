# Native menu pointer correction

The completed durable candidate attempt failed at the menu helper's native click receipt after mixed read and pin checks. Its whole return and independent holder closure are complete. The original runtime evidence has no click-time recipient or geometry, so the sole cause is unproved.

The existing `open_menu` helper now obtains an exposed cell from Screen's original committed widget bounds and clip, intersected with the screen. It checks native hit ownership and sends the real Pilot gesture with a row-relative offset. The prior assumption that `row.region.offset` is exposed is removed. No forced target, synthetic Click, fallback point or retry was added. The recipient and mounted menu remain required.

Only `open_menu` changed in this commit; its five consumers share this correction. Original source/dependency traversal parsed 980 modules with zero omissions; compilation without imports and diff check passed. No App, package installation, provider input or native authority was repeated. This is a helper correction, not a demonstrated production or latency fix.

Prior branch commits retain original task/scene capture at action-completion failure. The last run failed before that boundary; no such capture is claimed.

Next: verify the corrected helper through one fresh affected App attempt on the retained durable candidate, then continue actual publication and sidebar/frame latency acceptance. Candidate production remains unchanged; no wheel rebuild is needed for this helper change.
