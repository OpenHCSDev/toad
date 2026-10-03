# Existing native theme boundary and shared preference resources

Current main includes369. The generic RendererChoice imports Choice from setting_choices; that module also eagerly imports Textual BUILTIN_THEMES and declares the existing ThemeChoice family. Generic renderer selection consequently loads native widgets/toolkit declarations without using them.

Keep the original native ThemeChoice and authoritative Textual catalog together in their native module. Migrate every production/test ThemeChoice import; delete the old declaration/catalog and do not re-export it. Choice, the other declarations and RendererChoice retain their existing behavior. UiSettings still declares a native theme preference; that frontend contract is not converted into an invented generic family or an unchecked string. FieldCodec owns the unchanged durable choice names, while native ThemeChoice owns validation and labels.

The related shared PresentationBudget/demand module eagerly imports Widget solely for the original protected_presentations operation. Subject to Heisenberg's narrow import grant, acquire Widget in that existing native operation, with type references otherwise under TYPE_CHECKING. Do not change viewport methods, resource policy or ownership.

No class is added, no catalog is copied, no lifecycle or semantic state is duplicated. This is dependency deletion through the existing owners, not a cosmetic module relocation or a claim of full U2/U4 completion. Native theme/preferences intentionally retain their actual frontend contracts. Remaining native Markdown/Rich resources keep their original toolkit output contract.

Use existing refactor-audit AST evidence and read all declarations/consumers first. Implement the whole related import family, then final normal-baseline installed headless renderer selection and actual native theme/editor check. Reuse this checkout and the granted302 holder; no new environment/native/provider input/public changes. Optional persistent dependencies remain separately scoped. CI deferred.
