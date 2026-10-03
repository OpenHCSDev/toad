# Independent transcript preparation task boundary

The existing transcript fragment consumer and renderer task family already own grouping and worker behavior. However, transcript_preparation imports TranscriptRenderTask from the aggregate render_tasks module, which imports native MarkdownFence, PatchDiffView and Rich rendering resources. Headless source fragmenting therefore loads native widget classes it never uses.

Place the EXISTING TranscriptRenderTask and TranscriptBodyPreparation declarations with their original pure fragment owner. Migrate every declaration reference and caller in production/tests; delete the displaced catalog definitions/imports, without aliases, parallel task registries, new types or semantic state. Native Markdown preparation remains an actual body-dispatch operation and imports its original declared task there, not at core module startup. Preserve fragment grouping, source coverage, renderer admission, reusable result behavior and native source publication.

This is an import/lifecycle dependency deletion, not a widgets-directory rename. Native Rich/Markdown/patch resources retain their real Textual output contract. Native theme choices/preferences remain a separate unfinished boundary; no new frontend family introduced.

Heisenberg owns viewport/frame/registration methods; only consumer import references cross that claim. Same checkout/env constraints; Sch owns released485 and next receiver. Final validation checks clean headless imports, original process-fragment transport and affected actual installed App publication; no repeated366/368 check, native/provider call, public restart or frontend benchmark.

Source semantics and existing NRA AST first; coherent family migration/checkpoint, then batched end checks. Patterns IMPL-13 and MEMB-2. CI deferred.
