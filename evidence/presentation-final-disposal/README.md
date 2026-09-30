# Final presentation disposal

Owner: Heisenberg. Scoped checkpoint from PR217, based on current main7e4465c7. Remaining scrolling, focus and TC1/T9 work stays in PR217/221. No other owner's checkout was changed.

Actual installed crash: `Terminal_crash_2026-09-29T22_17_47_615136.txt`. AwaitRemove pruned Prompt before SessionView.on_unmount called OperationalSessionPresentation.close, which evicted the native tree and attempted SessionViewState.capture against missing editor children.

The workspace now finalizes a closing presentation before removing its view. Final disposal releases live bindings and rendering resources without capturing an editor nobody can return to. Bounded resource eviction still captures a live editor for return. Application shutdown uses final disposal too. The late on_unmount consumer is deleted; no query-exists guard, exception suppression, or replacement state store is added.

All changed disposal methods are structurally identical to the exact noneditable installed887 candidate. The relation is recorded in tested-method-relation.json. PR217 already has a physical saved-tab-close source proof. Exact installed physical saved-tab close and subsequent application shutdown are the remaining readiness gate for this checkpoint.

Seven production lines deleted, thirteen added across the three existing lifecycle owners. Existing foreign optional-resource probes are not claimed closed; the full TC1 presentation state work remains in PR217.
