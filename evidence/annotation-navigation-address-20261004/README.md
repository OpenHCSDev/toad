# Annotation navigation address

Successor to frozen functional Core627 e5f3811b and Toad434 75d5f0a0. Those branches and their installed evidence remain unchanged.

`WorkingMemoryAnnotations.address` owns the complete stored annotation address: segment digest, offset, length, question and version, classifier and pin. `ContextInspection.working_memory` now derives both grouping and node keys from that address through the original FieldCodec. It no longer assembles a second partial address. Answers and working-memory sections remain outside identity, so a HumanLabel refinement retains the same reader key.

The original segment membership admits contained overlapping ranges. Before this repair, same-offset ranges with different lengths shared a node key despite distinct storage addresses. ContextTree's node map, owns_node, reconciliation, reveal, reader-path traversal and retained intent all consume that key without parsing its fields. AnnotationSourceNode already traverses answer paths across section changes.

Before-source coverage uses original audit.findings.Package and FunctionFacts: 288 Toad production modules, 395 Toad tests, 324 Core modules and 249 pinned Textual modules; zero parse omissions. Calls are lexical evidence; native event dispatch and dynamic receiver resolution were read semantically.

The narrow authored check passed: **1 PASS / 1.44s**. Both same-offset ranges retain distinct owned native TreeNodes; their source paths resolve separately. HumanLabel refinement moves the short range to Obeys while retaining its key, selected span and detail. Unmount/remount restores that exact range and keeps the longer range distinct. The first constructor-only test negative is retained (missing authored Thread tags/worktree), with its corrected test setup.

This is source-only native Tree verification. The test uses an explicitly unsealed authored navigation model with no request ID or wire publication. It does not repeat or supersede the accepted registered GUI, create an SDK/native process, access an installed holder, or claim installed successor acceptance.

One normal source wheel was built using retained Hatchling 1.28.0, without isolation, dependency resolution or a new environment. All **319 Git/local/ZIP assets match**; only `src/toad/core/context_inspection.py` differs from the frozen qualified wheel. `source-proof.json` binds the exact wheel and producer revision. `PROPOSED-INSTALLED-OPERANDS.json` names one narrow future installed-owner check; it grants no holder access and repeats neither the accepted GUI nor the historical journey.

Functional Core627, stopped carry663 and Toad434 are now normally merged. This successor normally joined Toad main262875cb. Source, tests, tools, pyproject and uv bytes remain identical to tested build486fb213; the retained319-asset wheel and original narrow source result remain applicable. No rebuild or acceptance repeat was needed. The installed successor check is still unqualified and requires its own fresh holder purpose.
