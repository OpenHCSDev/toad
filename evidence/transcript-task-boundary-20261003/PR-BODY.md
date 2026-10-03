## Change

The existing fragment owner now declares `TranscriptRenderTask` and `TranscriptBodyPreparation`. Every production and test consumer uses that declaration. The old aggregate catalog definitions/imports are deleted, with no aliases or second task family. Generic source preparation no longer imports MarkdownFence, DiffView or native Rich rendering. `PersistentRenderClient.warm_up` acquires the original native tasks when warmup actually requests them.

Eight production files: **61 lines deleted, 57 added**. Existing task membership, rendering admission, reuse, cancellation, shutdown and native body behavior stay with their original owners. The task's module identity changes; existing renderer source fingerprinting separates ephemeral workers/caches. No durable native history or protocol carry is involved.

## Source and consumers

`before-owner-consumers.json` and `after-owner-consumers.json` record the existing refactor-audit AST package reader over 286 production modules, with zero parse omissions. There is one declaration of each moved task. Dynamic dispatch is not inferred from lexical AST; the installed checks cover the changed worker and App paths. IMPL-13 / MEMB-2: acquire existing capabilities at the operation that uses them, rather than loading an unrelated aggregate catalog.

Current main370 is normally integrated. Its receiving metadata/evidence changes leave this tested production source unchanged.

## Final installed validation

Reused the explicitly released302 holder, installing only the normal Toad wheel. All 69 packages are compatible; 293 source assets match the installed package byte for byte.

- Fresh installed import, original TaskCapture and actual spawned fragment worker: PASS, 1.617s. Textual and the native task catalog remain unloaded; workers close.
- Actual installed ToadApp, canonical decoded native history, moved fragment preparation, original native Markdown body dispatch and painted `Record 104`: PASS, 5.727s. App exits and the private generated fixture is removed, with no remaining borrowers.
- Original negative is preserved: the old fixture's assistant string content decodes as an invalid native record; the fixture now uses Pi's content array. The full navigation attempt then timed out at 60s; that result remains unqualified, and this PR makes no full scrolling claim.

No provider prompt, public input, default publication or native owner restart. No new environment/worktree. CI deferred.

## Limits and remaining scope

Normal69 qualification covers local worker/App behavior. No persistent-renderer extra was installed or retested; the warmup import placement is qualified by source closure. Prior366/368 optional qualification remains separate. Native Markdown/Rich resources intentionally retain their Textual output contract. Native theme choices/preferences remain an unfinished headless dependency boundary. No physical, latency, large-history or full U2 claim.

Receipts: `evidence/transcript-task-boundary-20261003/READY.json`, `installed-source-proof.json`, `installed-batch.json`, `installed-app03.json`, `cleanup.json`; raw negatives retained alongside them.
