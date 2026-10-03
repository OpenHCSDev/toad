## Review correction closed

Existing LineRecord.replace_content now acquires distinct mutable text and spans for construction and every replacement. Global blank Text is deleted; gap fill and both scroll directions use the same owner. add_line folds owned content. simplify mutates its own line. Installed Rich has no __iadd__ and copies through __add__, so _expand_content is unchanged.

Corrected production d5c19375636128d5dde5986408dab5b4e3e85dcc: **9 production files,201 added /454 deleted**. This correction is one file18+/14-. Final installed model isolation and installed03 realACP/Pi/PTY/Pilot both pass after normal wheel refresh in the same302 holder. Native acceptance body1.348s/0providerrequests; ownedfixtureprocessmatches0. No newenv/nativecopy/publicchanges. Original negative and previous receipts retained as history; current readiness is the corrected source.

NRA AST:286modules/0omissions/75relatedsites; sole content assignment is original LineRecord content.copy(). Evidence: mutable-content-before.json/mutable-content-after.json, model-isolation.json, installed03/terminal-model-receipt.json and native-terminal-model.svg. Canonical RECEIPT.json points to corrected source/installation. The earlier accepted checkpoint below is historical; qualifications for Pilot/physical/fullU4/U5 remain.

## Changed

The existing `TerminalState`, `Buffer` and `LineRecord` now own ANSI text, Rich styles/colors, cursor modes and geometry without importing Textual. The original native Terminal converts Rich text at its drawing boundary after checking its existing Strip cache. Original selection offsets and line folds are reused; native refolding and silent drawing-error suppression were deleted.

The original model owns the configurable 80×24 defaults. SurfaceBinding applies attached geometry through that model and leaves detached configuration intact. Stored widget width/height and repeated defaults were deleted. Keyboard events decode at the native view and use the original model's key encoding.

The final installed run exposed a real fast-command race: the child could read `stty size` before its PTY received geometry. `PtyProcess` now applies the same model dimensions before child spawn and shares its resize operation. Existing child custody, AsyncExitStack and terminal outcomes remain the lifetime owners.

## Source closure

Production: **9 files, 187 lines added / 444 deleted**, versus merged U2/main `8b81122c`. No new owner classes, aliases, codec or geometry record. The original Rich palette replaces the repeated 256-entry native-color table. The existing terminal contract test only migrates the color API (2+/2−), separately from production counts.

Existing NRA parser: 286 production modules, zero parse omissions; 12 original nominal definitions each occur once; 97 lexical owner references recorded. ANSI model has zero Textual imports; the only geometry-default declarations are on TerminalState. Rich/Textual dependency source hashes and actual fold-width contract are retained. AST does not prove arbitrary dynamic attribute resolution; actual callbacks/drawing are checked below.

Before/after evidence: `evidence/headless-terminal-state-u5-20261003/{before,after}-owner-consumers.json`.

## Final installed validation

Tested production source `e7c6ede5da01a545f3e24393f6916c51c764cf22`, reused 302 installed holder, Core `325e9f35`, Textual `940880e1`, SDK 0.12.1, native `960296fdddafb01c`. Normal wheel install; 314 installed source/resource files matched, 69 actual distributions; existing runtime-probe/native-manifest preflight passed. No source overlay/new environment/native copy or public/default mutation.

- Installed model/execution import does not load Textual. ANSI colors, Unicode, overwrite, cursor replies, keyboard modes, positive/height-only geometry, 196,800-byte incremental stream and reflow pass. Stream measurement 0.185 seconds is this bounded model workload, not an application speed claim.
- Actual installed Toad/ACP/Pi attachment plus real PTYs and Textual Pilot: 1,200-line truecolor/CJK/emoji output, visible native terminal drawing and original selection; configured detached 57×13 and default detached 80×24 sizes visible to the command; tab return reuses the same state and native process; both original terminal operations release. Acceptance body 1.457 seconds; zero provider requests.
- `installed01` preserves the original 0×0 PTY failure. Two model oracle corrections and their raw logs are retained; neither caused a production workaround. Existing PTY EOF `OSError(5)` prints remain explicitly recorded, so there is no zero-stderr claim.
- Fixture teardown completed; zero readable owned-process matches, zero inaccessible `/proc` entries in the cleanup observation. Original fixture roots and raw protocol logs retained.

Canonical scoped receipt: `evidence/headless-terminal-state-u5-20261003/RECEIPT.json`; actual drawing: `installed02/native-terminal-model.svg`; actual terminal result: `installed02/terminal-model-receipt.json`.

## Scope

Ready for this terminal owner/projection checkpoint. This is installed ACP/real-PTY/Pilot validation, **not physical st acceptance, a performance improvement claim, or complete U4/U5 delivery**. Generic view registration and remaining headless-plan work continue independently. CI is deferred; pytest is absent from the reused holder and no dev environment was created just to run it. Parent owns merge and public installation.
