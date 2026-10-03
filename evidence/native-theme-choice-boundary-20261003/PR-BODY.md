## Existing owner and dependency deletion

Generic renderer selection imported `Choice` from a module that also eagerly loaded Textual's theme catalog. The existing `ThemeChoice` family and its native catalog now live together in `native_themes`; all production/test consumers use that original declaration. The shared choice base remains independent. No new family, catalog copy, alias, unchecked string preference or frontend framework is introduced.

The original shared budget/demand module imports Widget only when its native `protected_presentations` operation runs. Heisenberg granted this import-only change; all budget, demand and viewport methods retain their original behavior. Both real callers, committed presentation and history anchoring, continue using the same protection helper. An initial claim that this helper was unused was immediately corrected from the full consumer evidence; no deletion occurred.

**Five production files: 24 lines deleted, 33 added.** The dependency change is meaningful: generic Choice/settings/budget/LocalRenderer selection no longer loads Textual, while explicit native themes keep their actual toolkit contract.

## Complete source family

Existing refactor-audit AST parses 287 production and 391 test modules after the batch, with zero parse omissions. Before/after declarations, imports, annotations and consumers are committed. One `ThemeChoice` declaration remains; its four test import consumers and two production consumers are migrated. No old-module re-export exists.

FieldCodec still encodes the original declared theme name, not its Python module. The saved preference shape and all native theme names are unchanged; there is no durable carry. Theme objects and labels derive directly from the same Textual BUILTIN_THEMES declarations. Lexical AST does not claim to resolve arbitrary dynamic imports.

## Final installed checks

Reused the granted302 holder and installed only the normal Toad wheel: all 69 distributions compatible, all 294 source assets byte-identical. No optional packages added.

- Fresh generic Choice/settings/budget/local renderer import/start/close with no Textual loaded.
- Every native theme name decodes/encodes through FieldCodec; native objects are the actual authoritative Textual declarations.
- **Actual installed ToadApp: F2 → original ChoiceEditor keyboard selection → native theme effect → Escape → saved `ansi-light` preference. PASS, 6.277s.** No substituted application, state, renderer or protocol.
- Original native protection helper member/nonmember call sanity passed; this checks that moving Widget acquisition preserves its runtime binding.

Private generated fixture removed, no remaining owned borrowers. No provider prompts, public inputs/defaults, native owner restarts, new worktrees or environments. Existing originals/UNKNOWN and raw369 negatives retained. CI deferred.

## Limits

This closes generic renderer/preference-resource coupling, not full U2/U4. UiSettings still deliberately declares a native theme preference and therefore loads native themes. Native settings editors, Markdown/Rich and widget rendering keep their actual Textual contracts. Persistent-renderer optional dependencies are not retested or claimed. No physical/default, large-history, scrolling or performance claim.

The369 navigation timeout is handed directly to Heisenberg/Kepler. Its 60s wrapper timeout and empty log cannot locate a frame/navigation/product cause; no unchanged rerun was performed.

Receipts: `evidence/native-theme-choice-boundary-20261003/READY.json`, `installed01.json`, `installed01.log`, `installed-source-proof.json`, `cleanup.json`, before/after owner-consumer JSON.
