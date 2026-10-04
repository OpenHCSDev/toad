# Unchanged loaded-reader resources across logical tab cohorts

Source-only successor of #443 at f3fb7ebc2878ed946f1217f2d38872d34c219d91.
No prefix, package, App, provider, native input or physical recording access.
#443's published qualifier and installed-only projection control stay unchanged.

## Existing owner and consumers

`ReaderCheckpoint` was confined to the saved-state A/B/A control. It already
owned editor/document/history, reader position, composited message text, weak
Markdown body references and the original render-cache resources. The existing
4/16/32/64 control checked attachment/editor/queue/painted-answer continuity but
could pass without proving unchanged native body/cache reuse at those cohorts.

The original class now lives with the existing recent-reader control and is
consumed by both the saved-state and logical-cohort controls. Capture observes
the current source; the saved-state caller retains its original non-tail scroll,
draft, history checkpoint and Undo setup. No snapshot method changes user state.
The checkpoint additionally observes the original committed page instances and
their prepared fragment tuples, tail intent and actual unsent text. Its original
reader binding owns raw page-read observation for both consumers (IMPL-12).
No competing checkpoint implementation, new fixture, loader or renderer exists.

Each logical cohort captures the two actual loaded native sources before its
three visit phases. Every unchanged loaded-source return must retain the
observed fragments, Markdown/render resources, reader/editor and composited
message text, and perform zero additional raw page acquisition. New input and
queue delivery follow these visit phases; the next cohort captures the genuinely
changed source anew. Blank logical tabs never earn loaded-history credit.

## Scope and remaining qualification

These are authored localhost-response controls on the existing installed
App/ACP/native fixture. They are not configured-provider, terminal-pixel,
CPU-gain, all-64-loaded-history or runtime PASS evidence. Captured reader
positions are reported; a tail-only source cannot earn a non-tail claim.
The original configured SDK fork, readonly guards and input dispositions remain
unchanged. Full continuous startup/channel/unopened-thread/fork-before-answer/
reply/notification/queue/status workflow and velocity/reversal/growing-End/
warm returns remain unfinished until their actual admitted executions.

The complete original refactor-audit Package census covers 288 Toad production,
395 tests, 41 tools and 249 retained native59 production modules, with zero parse
omissions. Lexical references were read against their existing owners; external
dynamic aliases and runtime equivalence are not proved by AST.

No private holder is requested or reserved by this source checkpoint. Public444
style22 is protected; any future qualification needs an eligible actual floor,
its archive/origins/keepers and a specific granted purpose. No old1470 restore.
