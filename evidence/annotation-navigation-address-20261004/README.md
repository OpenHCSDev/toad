# Annotation navigation address

Successor to frozen functional Core627 e5f3811b and Toad434 75d5f0a0. Those branches and their installed evidence remain unchanged.

`WorkingMemoryAnnotations.address` owns the complete stored annotation address: segment digest, offset, length, question and version, classifier and pin. `ContextInspection.working_memory` now derives both grouping and node keys from that address through the original FieldCodec. It no longer assembles a second partial address. Answers and working-memory sections remain outside identity, so a HumanLabel refinement retains the same reader key.

The original segment membership admits contained overlapping ranges. Before this repair, same-offset ranges with different lengths shared a node key despite distinct storage addresses. ContextTree's node map, owns_node, reconciliation, reveal, reader-path traversal and retained intent all consume that key without parsing its fields. AnnotationSourceNode already traverses answer paths across section changes.

Before-source coverage uses original audit.findings.Package and FunctionFacts: 288 Toad production modules, 395 Toad tests, 324 Core modules and 249 pinned Textual modules; zero parse omissions. Calls are lexical evidence; native event dispatch and dynamic receiver resolution were read semantically.

Verification pending: narrow authored overlapping-range identity and native Tree restoration. This is a source-only successor, with no installed package, SDK/native process, input, provider or accepted GUI repeat.
