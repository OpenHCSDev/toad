# Patch preparation and renderer boundary ownership

The existing Patch owns reported hunk coordinates. PreparedPatch owns the highlighted resource and its theme. Worker prepare_patch and native PatchDiffView currently repeat the syntax/inline preparation pipeline. Move preparation onto Patch and style binding onto PreparedPatch; both callers borrow those behaviors. Preserve the native style, mount, geometry, and theme publication owners. No new class, semantic field, cache or registry.

TaskCapture already validates declared task membership after unpickling imports its declaring module. Remove render_protocol eager imports of native task catalogs; generic transport must not select frontend operation members. Existing renderer source fingerprint and exact task contract remain intact.

Correction to the prior broad U2 lead: transcript_fragments, AgentActivityBoundary and message_filter have no Textual imports. Their widgets module paths alone are not evidence of frontend coupling. This batch does not relocate them or claim the entire rendering domain is frontend independent. DiffView remains the native highlighting dependency; no algorithm copy into a new highlighter owner.

Heisenberg granted only PatchDiffView.highlighted_code_lines fallback and pure preparation ownership; style registration/materialization/layout remain his. Sch owns receiving and the released private485 holder. Same checkout, no new environment or worktree.

Order: source/AST and full caller migration, coherent checkpoint, final affected installed patch/publication and task-boundary sanity. No provider inputs, public owner restart or repeated366 journey. Patterns IMPL-12 and MEMB-2.
