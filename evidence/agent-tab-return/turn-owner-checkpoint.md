# Turn owner checkpoint, 2026-09-29

`TurnOwner` now carries activity text and elapsed-time origin. The ACP Agent keeps
the current managed turn; the selected Conversation projects that owner to its
activity row, prompt and throbber. The previous independent activity and timer
reactives, and managed-turn busy-count increments, were removed. Independent
local work still contributes to the throbber through its own count.

The noneditable installed Toad wheel, pinned core b72e97ce, pinned Textual
609b74bf and verified native Pi package ran the two-saved-history A/B/A journey
with a localhost provider. It checked an idle destination while the other
source had an active turn, activity and throbber after settlement, and both on
return. First run passed. After the Agent became the activity authority, one
run exposed a blank first frame on active return; a second run passed the full
journey. This is an intermittent retained-history readiness defect, not a green
first-frame acceptance. Its failing receipt is retained in the owned scratch
directory `toad-pr194-turn-20260929/native-turn.log`; the passing rerun is
`native-turn2.log`. The focused direct T4 turn/navigation tests passed twice.

Still open in PR #194: eliminate the blank first frame and visible message
reloading on tab return, and reproduce/fix scrolling past the history end.
