## What changed

ShellOperationalSource keeps its original PTY, task, output models and serialized attachment lifetime. It no longer reaches through Conversation/app. Existing SurfaceBinding owns shell native creation, directory/dimension preparation and error notification; native presentation uses its existing MRO dispatcher. The same existing binding family is shared by agent and shell; no retired controller export or second definition.

ShellResult now borrows the original command output instead of copying text. Returning to a retained view reuses command/terminal widgets by their source/model identity. No seen list, cache, new class or frontend registry. Process cleanup lives once in the existing source base. All creation/start/session detach/reattach/output/clipboard consumers migrated together.

**Ten production files:138 additions /110 deletions.** Counts include relocating the existing surface declaration; zero new types. [Scope and deleted paths](evidence/headless-shell-surface-20261003/SCOPE.md), [before](evidence/headless-shell-surface-20261003/before-final-family.json), [after](evidence/headless-shell-surface-20261003/after-owner-consumers.json). Existing parser covers288 production/391 test modules with zero omissions and one declaration per owner. Generic/dynamic resolution requires source reading; full external dependency AST is not claimed. Patterns BOUND-2/AGENT-2/IMPL-12.

## Final installed result

[READY](evidence/headless-shell-surface-20261003/READY.json), [source proof](evidence/headless-shell-surface-20261003/installed03-source-proof.json), [actual App/PTY log](evidence/headless-shell-surface-20261003/installed03.log), [original resource/presentation facts](evidence/headless-shell-surface-20261003/installed03/shell-publication.json), [viewed PNG](evidence/headless-shell-surface-20261003/installed03/retained-shell.png). Actual installed retained-shell journey passed: original command/terminal widget/model/task/process, detached output, tab clicks, terminal-body paint, directory event, subscription retirement, clipboard, editor/drafts/undo and logical-close process/reader retirement. PNG readable with one command caption. Source319Toad/342Core/266Text38 assets exact;69 distributions/SDK0.12.1. Existing released485 only; no new environment/native copy/provider run. Normal382/Text38 joined.

Original01 failed an obsolete private Signal count before shell, preserved;02 passed shell behavior but showed the duplicated caption, preserved and corrected in this family. Original first Text37 preflight is historical; canonical current proof is installed03/Text38. NO_COLOR removed explicitly for exported-color qualification; prior black exports retained.

Holder released to Bohr at terminal; original activation/native044/evidence/UNKNOWN and all public/default owners untouched. No physical st/FPS/latency/native-Pi/provider/ACP-admission/full headless-plan claim. CI deferred.
