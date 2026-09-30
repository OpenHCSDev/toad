# Final presentation disposal

Owner: Heisenberg. Scoped checkpoint from PR217, based on current main7e4465c7. Remaining scrolling, focus and TC1/T9 work stays in PR217/221. No other owner's checkout was changed.

Actual installed crash: `Terminal_crash_2026-09-29T22_17_47_615136.txt`. AwaitRemove pruned Prompt before SessionView.on_unmount called OperationalSessionPresentation.close, which evicted the native tree and attempted SessionViewState.capture against missing editor children.

The workspace now finalizes a closing presentation before removing its view. Final disposal releases live bindings and rendering resources without capturing an editor nobody can return to. Bounded resource eviction still captures a live editor for return. Application shutdown uses final disposal too. The late on_unmount consumer is deleted; no query-exists guard, exception suppression, or replacement state store is added.

All changed disposal methods are structurally identical to the exact noneditable installed887 candidate. The relation is recorded in tested-method-relation.json. Actual installed887 physical saved-tab close and subsequent application shutdown PASS: 20.861 seconds, original view absent after click, no NoMatches/traceback, zero cleanup errors or remaining owned processes, original native owner alive and unchanged. Before/after PNG and installed887-close-receipt.json retain evidence. Before/after SVG is diagnostic observer work, not necessarily the preceding terminal frame.

Closing the final tab automatically opened nominal-refactor-advisor-3. Its newly registered owner was recorded with zero turns, no session and no active turn; there was no prompt action. Registration/history are preserved, and separately authorized owned cleanup requires fresh actual idle/identity verification.

The parent explicitly accepts the installed887 entrypoint proof plus exact changed-method identity for merging this checkpoint. ONE exact222/default physical close/open/shutdown verification is deferred to activation, using two existing tabs to avoid the final-tab automatic new-thread action. No duplicate pre/post acceptance runs are planned. Scrolling remains failed in PR217/221 and is not a gate for this usage-blocking disposal correction.

Seven production lines deleted, thirteen added across the three existing lifecycle owners. Existing foreign optional-resource probes are not claimed closed; the full TC1 presentation state work remains in PR217.
