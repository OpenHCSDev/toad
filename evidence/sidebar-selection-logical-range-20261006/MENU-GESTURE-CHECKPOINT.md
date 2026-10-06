# Native menu click ownership

ContextMenuItem now activates from the original native Click, retaining mouse-down/up/leave only for pressed styling. The custom _pressed matching decision is deleted. Its existing message consumer migrates from Pressed to Selected; keyboard selection and outside dismissal remain unchanged.

Before: ContextMenuItem posts activation during MouseUp; ContextMenu may dismiss while App awaits that delivery. App then acquires release geometry to create Click, so the menu can disappear before native click admission. After: native App owns matching and emits Click before the item requests dismissal.

Original Package parsed 288 production, 403 test, 40 tool and 249 native modules without omissions; 33 related modules indexed. No external Pressed consumer was found. Source parse/compile and diff check passed without imports.

Batch06 initially passed Shift and Ctrl mixed selection then returned false on mixed read-target click. This source ordering counterexample does not establish its sole runtime cause. Its restored whole return/raw/journals remain immutable. Fresh affected installed App acceptance is outstanding; no runtime or latency claim.

Focused real native App check passed using original run_test/Pilot and the corrected ContextMenu: native Click reached the original item, selected read-target and dismissed the menu. Interpreter /usr/bin/python with actual native77 and this Toad source; no installed prefix, backend batch or public runtime was exercised. Full selected-target installed acceptance remains outstanding.
