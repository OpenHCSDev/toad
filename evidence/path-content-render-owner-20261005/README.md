# PathContent uses the native render owner

Source continuation from frozen460 `22177726`. The installed7546 wheel,
its original953/full74 proof, and the issued renderer/cold controls are separate.

`PathContent` owns path shortening and its fixed nowrap/clip/left/zero-pad
policy. Native `Content.render_strips` owns formatting, height projection and
strip construction. The sole Toad private `_wrap_and_format` caller and its
copied height slicing/strip loop are removed (IMPL-12).

`dataclasses.replace` retains the original `RenderOptions` selection,
selection style, post style and style resolver references. Only four authored
path policy rules are replaced. Path shortening, zero width and native tab8
remain the original contracts. Positive, zero, negative and unbounded height
follow the same native public projection. `PreparedDiffLine` already inherits
that owner and needs no migration.

Before: original refactor-audit Package/Repository parsed288 ToAd production,
397 tests,41 tools,324 Core and249 Textual production/460 tests; zero omissions.
All11 related declaration/call sites are in OWNER-BEFORE.json.
After at determining `1fbe1f09`, the same complete roots parse with zero
omissions. OWNER-AFTER.json records zero private formatter consumers anywhere
in Toad production, tests or tools. Native consumers retain their existing owner.

SOURCE-CHECK.json records syntax compilation and the original audit measure
comparison. No positive structural counters. The first authored audit call
omitted its required path argument; that negative is retained in the receipt.

Native70 is a source dependency only. Source checks do not qualify an installed
path picker, useful first paint, moving frames, CPU or speed. No App, package,
wheel, prefix import, capture or provider operation belongs to this checkpoint.
Final native public projection controls remain Kepler's native owner scope;
the next changed installed frame cohort is separate from the frozen460 purpose.
