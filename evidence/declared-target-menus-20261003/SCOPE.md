# Native menus for backend-declared operations

Draft implementation; no installed readiness claim.

Replace the frontend thread/channel operation catalog with the existing backend
CliCommand query, parameter metadata, confirmation and typed execution. Toad
owns native menu/form display, route-bound request lifetime and navigation.
Tags edit, channel rename/delete and saved-view deletion use ChannelManagement.
Delete frontend semantic option lists and repeated domain operation bodies.
CoreEventReceiver, MainScreen delivery and viewport/preparation are excluded.

Source/AST ownership first; implement all consumers; one batched sanity and
actual installed right-click/CLI private-bus journey last. No provider/input
replay, new checkout/environment or public publication. Native frontend-only
copy/close navigation remain frontend operations.

## Catalog read ownership correction

The old `CommandCatalog.entries` property synchronously queried backend
applicability on every slash projection and execution. It is replaced by
`CommandCatalog.read`: one transient acquired projection for each refresh or
execution, read through the original PreparationRuntime worker. Right-click,
initial/advertised/open-tab updates and both native/channel submission consumers
use that owner. The original native Worker cancels replaced completion reads;
route selection, selected session and attached agent fence delivery. Completion
resources contain display values, never a widget-owned applicability authority.

The native Conversation's extra synchronous registry presence read is deleted.
Channel chat's retired TargetContext.decode call and per-history-poll catalog
read are deleted. Existing CoordinationObserved publication refreshes both
native and channel completions, including retained hidden views. The original
session owns their target mode; global selected mode cannot retarget a hidden
view's command. Action service acquisition and guarded writes also borrow the
existing preparation worker. No new polling, registry, cache or state flag.

Current checkpoint is source implementation, not installed readiness. Final
changed installed journey includes slash refresh/execution, pointer operations,
backend changes while open/hidden and saved reopen. Existing inherited source
batch negatives and all prior evidence remain unchanged.
