# Publish native style mutations from their existing owner

Reuse the finished native checkout; Text29 and Text30 remain frozen independently.

Styles owns its rule dictionary and mutation notification. Detached parse/serialization rule resources currently invalidate every native inherited-paint cache despite having no linked DOM node. reset/merge/merge_rules also publish a mutation when the original dictionary has not changed. RenderStyles delegates inline mutation to Styles but repeats bookkeeping for reset/merge_rules.

Read the existing style family and all callers first. Extend Styles to publish only actual changes through its original node relation; merge delegates the original rules merge algorithm. Keep real linked rule writes and their epochs immediate, including inside batch_update. Preserve refresh, animation, layout, ancestry and original subtree resource contracts. No new cache, epoch, type, deferred mutation or Toad change.

The 05 physical movie shows mounting/style/layout during discrete movement. It does not establish which work dominates a stall. This change removes confirmed unrelated invalidation, not a measured speed claim. Changed installed qualification belongs to Heisenberg's next combined workflow; no extra capture/provider/environment or unchanged gate.

Source/caller closure and deleted lines will be recorded with the implementation checkpoint. Proportionate affected sanity comes after coherent implementation, then the joined real application path.

## Published source checkpoint

Production source `7589f2733d6d48251b73f0b76014c6bf149080a4` changes
two files: `src/textual/css/styles.py` (12 added, 10 deleted) and
`src/textual/dom.py` (one deleted). This draft is stacked on frozen Text30;
qualified Text29 remains independently shippable.

Styles remains the single rule-mutation owner. `_mark_updated` always advances
the changed rule resource's own key; only its original linked DOM node advances
the global inherited-paint epoch and publishes the existing subtree revision.
Detached parse/serialization resources keep their own usable rule keys without
invalidating unrelated native widgets. Genuine linked writes remain immediate,
including reads within `batch_update`; no new deferred epoch was introduced.

`merge` now calls the existing `merge_rules` algorithm. That algorithm detects
actual key/value changes before updating the original dictionary, including the
distinction between a missing key and an explicit initial `None` declaration.
Resetting nonempty rules publishes their removal; resetting empty rules does
not invent a mutation. Existing descriptor validation, refresh batching,
animation callbacks and subclass notification hooks remain intact.

Deleted the RenderStyles `_updates` field and its independent writes in
`merge_rules`, `reset` and DOMNode's component-style collection. RenderStyles
`_cache_key` now derives from the original base and inline Styles keys. Both
sources remain fixed for that view's lifetime; component collection constructs
a fresh view and merges into its original sources. No replacement counter,
new class, cache, geometry map or Toad state was introduced.

## Source and consumer evidence

Existing NRA `Package.load(Repository(...))` parsed all 249 Textual and all 276
Toad production modules before and after the edit, with no parse omissions.
Recorded declaration/read/write output is retained in:

- `.artifacts/native-style-source31/owner-before.json`
- `.artifacts/native-style-source31/owner-after.json`

The query returned 65 sites before and 60 after. These include explicitly
unrelated native `batch_update` and revision references; dynamic descriptor
dispatch is not proven by attribute matching. Original sites were read:
StylesBase/Styles/RenderStyles; Stylesheet.replace_rules and component matching;
DOMNode.set_styles, component collection and inherited-paint resolution;
StylesBuilder's detached construction; and native Widget/compositor plus Toad
body consumers of the published subtree revision. The five removed sites are
the extra view counter's declaration, read and three writes. Local Styles
mutation and the single DOM subtree publication remain.

StylesBuilder's raw dictionary writes construct detached declarations before
publication; they do not mutate mounted DOM sources. Styles.parse binds its
optional node after construction. Weak node ownership and custom ancestor
resolution remain unchanged. No fallback reader or compatibility field was
retained.

## Final affected sanity and remaining live boundary

After the coherent implementation, one batch passed 107 checks in 1.33 seconds:
`tests/css/test_styles.py`, `tests/css/test_stylesheet.py` and
`tests/test_inherited_paint_projection.py`. These cover value/initial rules,
bulk writes/removals, inherited paint and ancestry moves, weak ownership,
component styles, animation and nested/interrupted refresh batching. One added
continuous native-source check confirms that detached serialization and equal
rules preserve the paint epoch, while genuine bulk writes/removals are visible
inside the existing update lifetime. No UI/protocol/provider mocks were added.

The 05 movie/profile establishes mounting, style propagation and layout during
readable but discrete motion. It does not attribute CPU time to this deletion.
This source is NOT installed-qualified or Ready. Heisenberg owns the next single
changed installed 30/31 workflow; no new environment, capture or provider call
was made here. Text29/331 scoped shipment is independent.
