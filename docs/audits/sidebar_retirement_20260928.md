# Revealed sidebar retirement acceptance

Noether owns thread-sidebar declarations, retirement/restoration and project
reader intent. Tesla owns App/MainScreen/workspace/shell/terminal and switching
performance. PR136 merged into PR129's base branch, not main. Parent owns final
integration and live installation.

## Production boundary

`SessionThreadSidebar.prepare_presentation()` and `retire_presentation()` are
awaited by Tesla's MainScreen owner (5fcdb93), under existing serialized workspace
admission. No new pool, bound, owner store or deferred retirement worker exists.
Merged137's non-DOM ConversationBlock and native widget CSS ownership are retained.

SessionPanel uses core's existing DeclaredFamily. Each declaration constructs its
own admitted widget and captures its reader intent; the composition is derived
from members, with a new-case guard. Existing RelationshipTreeState objects retain
identity/selection/collapse/scroll. Existing SidebarState retains pane collapse and
scroll. Plan retains the latest typed source entries, never events. ProjectTreeIntent
retains filesystem identities and offsets, never TreeNodes or widgets. Restore
uses the original DirectoryTree loader; its scroll applies after native expansion
and resize settle. A changed project does not inherit the former root's navigation.

Retirement cancels and awaits actual hydration before capture/removal, unmounts
panel/control children and clears rich references. The original five-widget
retained construction and its once-revealed lifetime assumptions are deleted.
Two obsolete retained-widget/mocked observation pilots (218 lines) are deleted.

## Executed installed acceptance

Noneditable installed Toad with core4510dddf and merged Textualc9743801. Local
filesystem and actual core relationship service; no patched MainScreen, mock
source, provider calls, live configuration writes or CI wait.

- 64 tabs each revealed and returned through ordinary installed MainScreen/App
  selection. Cohorts4/16/32/64 each retain exactly5 rich panels on the selected tab;
  inactive tabs retain none. All321 retired panel/tree weak references collected.
- Original relationship state object, selected identity and disclosure restored.
  Expanded directory paths, selected file, scroll and current project restored.
  Plan changed while absent appears on return without replay.
- Actual compositor strips cropped to native visible widget geometry and clip
  contain returned plan words, selected file after native scrolling, and selected
  relationship text. Screenshot `evidence/sidebar-retirement/sidebar-return.svg`.
  Counts/mounted nodes alone do not satisfy this check.
- Scale pilot passes43.11s. Separate repeated lifetime/project-change/in-flight
  hydration cancellation/normal switch-return and ownership/deletion guards:
  **4 passed8.58s**. In-flight worker is cancelled/awaited by the production hook.

64-tab UI RSS145,702,912bytes (~139MiB),1167 asyncio tasks. Settled rich-sidebar
return median247.58ms/max314.92ms. This includes sidebar reconstruction and20ms
pilot settle; it is headless installed UI timing, not terminal latency or a
performance improvement claim. Tesla retains the measured switching regression.

## Ownership / refactoring evidence

Complete configured NRA package+dependency JSON scan finished39.31s within220s
budget:420 files,221 Toad plus199 installed core context;30 supporting raw findings,
25 R1. None locate the five owned modules. This CLI profile exposes no separate
scan_status/detector-omission fields; do not interpret that as proof every detector
ran. Compressed full receipt retained. Authored lifecycle changes are validated by
the executed installed pilots, not asserted to have native equivalence proof.

Owned per-class AST span: SessionThreadSidebar70→38; ProjectPanel48→48,
ProjectSearchButton29→29, FilePreview84→84. No preexisting owned class grows.
New owners have their first baseline here. Production adds more than it deletes
because the former implementation retained widget graphs rather than providing
state capture, cancellation and reconstruction ownership.

Final receipt/provenance, scale metrics, scoped ratchet, compressed NRA material
and screenshot live in `evidence/sidebar-retirement/`. Completed disposable test
roots were cleaned; source/worktree and bounded receipts remain persistent.
