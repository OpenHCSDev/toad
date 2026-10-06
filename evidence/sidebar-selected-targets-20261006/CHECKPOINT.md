# Sidebar selected targets

Parent owns the Toad integration. Backend API is Core696 at 7227262c65b91a1e0ad65a514ab95e38825c7bd8; native pointer FIFO implementation is 3e73a51ab881d8d9cddfc6f60a57ee4453854dfc. Neither is relabeled as public installed acceptance.

SidebarState retains selection intent; its existing selected row is the range anchor. SidebarNavigation owns Ctrl toggle, Shift native row range and selection paint. Normal activation retains single-target navigation. Right-click preserves an existing selection or selects the clicked row without focusing or scrolling it. Thread and channel rows share this path.

Existing NavigationTarget.menu_context supplies the target-specific single context. SidebarNavigation extends it with the selected target tuple and each original row's channel, deduplicating backend names. TargetContext acquires the original backend catalog; no UI availability list, membership copy or action dispatcher was added. TargetAction owns editable parameters and confirmation. Both old confirmation() consumers now read the property, and TargetEdit gets the action targets. ThreadActions associates one task with each selected target, joins it once and uses original successful reconnect results. Typed partial outcomes produce an error notification with the actual completed count and each failed target; no blanket success or rollback claim.

The original codec-derived tag-disposition field already exposes Core696's inactive exact-tag deletion choice. No duplicate selector or tag-deletion implementation was added to Toad.

Before source work the existing refactor-audit Package enumerated the related Toad/Core production, tests and tools (1,484 parsed entries), including all selection/confirmation/TargetEdit/reconnect consumers. Changed seven modules parse and compile without imports; git diffcheck passes. Dynamic source dispatch is not claimed from AST alone.

One real private App/HeadlessDriver journey passed against the actual Core696 and native73 sources: Ctrl toggle; Shift range; unchanged active conversation; retained right-click batch; original read-parameter dialog and private human read operation; original two-thread archive with the unselected thread retained; mixed channel/thread catalog with per-row channel context; then a real status change between catalog acquisition and execution causing one archive success and one refusal. Original App notification reports 1/2 completed, severity error and the failed name. No mocks, handler replacements, native agent launch, provider input or public operation.

Raw logs are retained under /home/ts/.cache/agent-scratch/parent-sidebar-selection-20261006. The first fixture used Registration's default running status and therefore correctly had no archive action. Corrected fixture declares stopped threads. A second test incorrectly expected an archive parameter dialog; archive has no editable fields or warning. The final journey uses the actual read-target dialog, then original immediate archive. Both initial negatives are held. Final mounted-partial stdout reports PASS and stderr is empty.

This is mounted source App acceptance. Combined installed UI/native/provider acceptance and the public cutover are pending. Core696 and this consumer change must be integrated together; no installed package, pin, live App or other agent checkout was modified.
