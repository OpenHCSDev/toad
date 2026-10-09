# Focus rule supply

The existing RuleSet parser owns pseudo-class dependencies from every selector, including ancestor and nested selectors. Stylesheet.rules_map now indexes those declarations alongside target names. Focus/blur/focus-within acquisition selects indexed rules and deletes its scan of every rule for every changed scope. Actual dynamic selector checks, nested-scope target traversal, component/virtual DOM handling and cascade application remain unchanged. Candidate collection unions rule identities; cascade precedence still comes from the unchanged apply path.

The rules_map reader first acquires rules, so a pending read/parse cannot serve an older index. Successful parse and reparse retire the same existing index; copies retain their normal source/parse lifetime. New pseudo-class keys cannot collide with native target keys (type, *, #id, .class). No new cache or registry.

AST before: 249 native production, 467 test and 288 Toad production modules, zero omissions. RuleSet._post_parse is the dependency producer; Stylesheet.rules_map is the one index; App application focus, Widget focus and Screen changed focus-within scopes converge on _update_focus_dependencies. Existing matching/index readers were inspected. After native parser: 249 modules, zero omissions. External dynamic mutation is not proven absent by lexical AST; no new support for post-parse selector mutation is claimed. Three production lines replaced; index lifetime and all three focus consumers use the existing owner.

Seven focused controls passed, including real mounted descendants/components across CSS read and reparse. One original matched sidebar App finished zero with empty stderr, 508 widgets/10 tabs, no provider. Right profile: same three focus updates, own declaration discovery 7.05ms -> .47ms and full method 19.03ms -> 11.22ms. Left full method 18.51ms -> 7.99ms. This is a single source headless observation. First-display medians 41.8/42.2ms versus 40.1/45.6ms, tails vary, paint was slower: no reliable overall frame or live speedup claim.

RESULT.json binds original raw profiles/logs and source evidence. No new build, install, provider, public operation or repeated benchmark. The existing empty-damage pending_for checkpoint remains on this same PR, independently scoped.

## Fresh live geometry profile followthrough

The existing sidebar-live-frame-profile-20261006 profile has two sampling errors. It shows deferred_regions under pending_for, and _damage_geometry under scrolling reflow; transition counts do not measure CPU time or damage state.

A concrete redundant decision remained in Compositor._damage_geometry: when the entire screen was already dirty, track_damage was false but the method still compared every new placement with the prior map. Those comparisons supplied no damage or resize result. The owner now wakes the original idle publication and returns immediately for that state; partial damage keeps both previous/current clipped rectangles and removed placements. Held exclusions still partition the retained full-screen damage at rendering. No root-bounds shortcut, ancestry index or cache.

Existing Package parsed 249 production modules with zero omissions: one _damage_geometry declaration, three callers in reflow/reflow_visible/full_map, no additional result consumers. New source compiles and diff-check passes. The prior CSS App result remains at 6c5c0a055, before this additional geometry change. No App/profile/control rerun or performance claim for this source-only reduction. Nonempty descendant geometry still requires the original membership/overflow relation; the samples alone do not establish redundant arrangement or its duration.
