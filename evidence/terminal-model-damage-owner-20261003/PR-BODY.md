## What changed

The existing ANSI model's damage result now reaches the tool terminal, just as it already reaches the shell terminal. Its existing cursor/screen mode classes declare their own damage. Returning to a retained terminal reconnects the same execution to the reused native widget through its original attach method; the model and process are retained.

**Four production files, 16 additions / 8 deletions; no new class, state store, cache or projection family.** Deleted the tool's per-chunk full-refresh decision and its lost callback on same-widget reuse. Initial/reattached state and final outcome still receive full projection. Existing binding/session/controller/currentness/retirement owners are unchanged.

## Source closure

[SCOPE](evidence/terminal-model-damage-owner-20261003/SCOPE.md), [before AST](evidence/terminal-model-damage-owner-20261003/before-owner-consumers.json), [after AST](evidence/terminal-model-damage-owner-20261003/after-owner-consumers.json). Existing refactor-audit parser: 287 production / 391 test modules, zero parse omissions. All original model, execution, shell, native terminal and binding consumers were read. Lexical references do not prove dynamic dispatch or full dependency resolution. Exact methods coordinated with Heis; no geometry/style/registration/viewport changes.

## Final installed validation

[READY](evidence/terminal-model-damage-owner-20261003/READY.json), [all318 source assets](evidence/terminal-model-damage-owner-20261003/installed-source-proof.json), [actual App/ACP/PTY log](evidence/terminal-model-damage-owner-20261003/installed02.log), [projection records](evidence/terminal-model-damage-owner-20261003/installed02/projections.json). Original installed fixture extended with --damage-only, no new environment/harness framework. Streaming/cursor/screen/detach/actual tab return/subsequent paint/exit7/retirement passed. Ten native projections, zero provider calls; original PTY masters 0→0 and child retired. Original failed01 capture/log preserved; source callback defect fixed, fixture command title and numeric completion oracle corrected.

Reused normal69 holder334 Core12c/Textb1/SDK0.12.1. Historical native9f12 not acquired. Main376 normally integrated with zero Toad production delta from tested source; its dependency metadata does not enlarge the fixture's baseline qualification. No native-Pi, physical st, latency/FPS or full headless-plan claim. Parent owns final receiving/publication. CI deferred.

## Exported visual limit

The original compositor/SVG text contains the final body after reattachment, but its exported foreground is black on black. [PNG](evidence/terminal-model-damage-owner-20261003/installed02/reattached-completed.png) is retained as a **negative artifact, not readable pixel acceptance**. The old normal69 donor Core12c/Textb1 differs from the merged receiver f109/c580; dependency/style mismatch is a possible cause, not a source-proven diagnosis. No color/style/viewport workaround or repeat provider/native run. The result qualifies the model/resource/callback/text path at its stated scope; the matched receiver must establish its own readable visual acceptance. Heis and parent informed.
