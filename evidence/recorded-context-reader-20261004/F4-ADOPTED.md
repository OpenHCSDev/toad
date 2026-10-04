# Shared F4 consumer adopted

Original Mendel425 commit afab8fe8be9a8a24e4ce71f3264a6ead561d5e06 was cherry-picked normally as 27a5fc9d4ff0f5439c92a727bdc2880156d18ffd into existing PR417.

Only ManifestNode.label and detail changed, two lines added/two deleted. Label calls SegmentManifest.public_description(); the detail title calls the original ContextSegment.public_title() through the manifest's kind. Tokens/bytes/digest/explanations remain unchanged. No string/type guard, codec or new label owner.

After adoption, Python AST comparison of the entire context_inspection module with those two granted methods excluded was identical. Compilation passed. State/Tree/search/read/export and both original node construction paths are unchanged. Mendel supplied the original whole Package consumer census; no duplicate broad scan or installed run was performed here.

This source requires the F4 producer relation: Core622 f32c709e declares SegmentManifest.kind as type[ContextSegment]. The earlier Core615 8f1633 branch pin still declares kind:str. No dependency pin or package was changed here; the final paired source metadata must join the reviewed F4 producer before an installed check. No runtime compatibility branch was added.

Mendel owns the pending installed decoded-contributor/recorded-label check in F4, independent of PR417's still-unfinished reader export/distinct child. Original physical10, the F3 source qualification and all negative/proof/UNKNOWN custody stay at their prior strength. No holder loan, artifact, environment, native, provider or capture action was inferred.
