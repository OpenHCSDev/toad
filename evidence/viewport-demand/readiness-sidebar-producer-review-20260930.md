# PR249 source producers and actual retained resource sizes

**Production lines deleted by Kepler: 0.** Read-only help for Heisenberg249, sole production/integration owner in `/home/ts/wt/toad-workspace-readiness-sidebar-continuation-20260930`. Pre-edit source is the normal main-based continuation after PR248. No new capture, provider call, public process action, native input, production patch, resource cache or clock.

## Initial native Mount and later content publication differ

Textual Markdown `_on_mount` at _markdown.py:1152 awaits its initial `update`. `update` at :1401 parses through the original parser/worker contract, then awaits native removal/mount batches. Widget Compose awaits child Mount, and AwaitMount joins each original child's mounted event. Thus initial Markdown parsing and native child admission are covered by the existing native Mount transaction, not a second watcher list.

Later `TranscriptFragmentView.update_fragment` at transcript_history.py:253 awaits either a text leaf update or native recompose. `TranscriptHistory.update_live` at :634 wraps current-page updates with the original history lock and `HistoryWindow.preserve_history`; that native tree lock is the frame-publication fence, not merely source status.

`StreamingMarkdown._publish_content` at streaming_markdown.py:157 sets `loading=False` **before** awaiting a newly created pager's Mount. Existing `_content_lock` owns this update, and original caller/source publication context matters. `loading=False` alone cannot certify that all later native children are mounted. Accepted source state similarly does not certify a subsequent recompose's descendants.

`TranscriptFragmentView.body_ready` currently checks nested ViewportBody readiness across a full descendant walk. `PreparedConversationMarkdown.body_ready` adds original Markdown loading. `_check_edges` instead checks every native descendant's Mount completion, including non-body controls. These are distinct obligations. Preserve their native producer contracts if moving repeated traversal into the existing declaration owners; do not substitute one bit for all three meanings.

## Corrected sidebar ownership lead

`SidebarProjection.channels` derives channel resources from original sidebar children. Each `SidebarGroup.member_container.children` owns current native row order; `reconcile_rows` sorts that same native container after awaits.

`ChannelGroup.member_rows` at comms_sidebar.py:76 is a **stored tuple**, assigned only after `_sync_members` awaits reconciliation at :165. It is not a derived property. It can retain old rows between native removal and completion of reconciliation. This corrects the earlier suggestion that the existing tuple directly supplies canonical native membership.

Use current `member_container.children` through the existing row/group declarations when eliminating whole-sidebar DOM queries. Close stored-order consumers in place if that ordering is replaced. The existing `_members` map is keyed native-resource construction/reuse, distinct from canonical ChannelView semantic membership; a new lookup/cache is unnecessary. No stale-row user failure was reproduced by this read-only review, so the asynchronous risk is stated as source evidence rather than a fabricated live bug.

Pre-edit all-consumer census: three production occurrences of `member_rows` (constructor, post-await assignment, SidebarProjection.rows) and ten test occurrences across channel_views_pilot.py(5), saved_state_user_journey_pilot.py(2), sidebar_custody_installed_journey.py(2), sidebar_metadata_reflow_pilot.py(1). Two concrete SidebarGroup users exist: ChannelGroup and RelationshipRows. RelationshipRows retains the shared reconciler's **local** returned order only for one scroll-compensation transaction; it has no persistent member_rows tuple. Preserve the shared return contract while deleting ChannelGroup's competing stored order and migrating its consumers.

## Source acceptance and paint invalidation must stay coherent

`SidebarPaint` currently includes the complete SidebarSnapshot plus expansion and pending action state. The snapshot contains full Core ThreadViews with runtime, last_seen, binding and goal/activity facts, plus session routes. For example, Core6feb AgentRuntimeInfo.timestamp is inside that equality, whereas ThreadRowsWork's exact display projection retains runtime.model but excludes context metrics/timestamp. A changed runtime timestamp with unchanged output can reach full rebuild even though worker-prepared row content is reusable. Reading runtime metadata does not itself restamp it, so this is not a claim that every poll rebuilds.

The existing caption/style consumers already guard unchanged values: CommsRow.set_label compares its current label, channel unread/activity updates compare values, SortControl checks its order/content, and ThreadStatusRow compares prepared content/signature and updates with layout=False. Do not diagnose an unconditional caption update without accounting for these declarations.

In `SidebarProjection.publish`, current snapshot acceptance happens only inside `rebuild`; the unchanged-paint branch does not refresh group snapshots or row targets. Narrowing equality to visible caption alone would therefore leave semantic menu/route/runtime metadata stale unless the same canonical publication accepts and delivers that source too. Current ChannelGroup presentation reprojects routes after its preparation await and refreshes existing row targets. Preserve those consumers through the existing publication owner while making native paint/layout proportional to actual output. No second source snapshot authority, render registry or status mirror is required.

## Actual PR248 body sizes are bounded

These are existing captured native DTOs from the sole actual A41MB/B13MB workflow, not a fresh synthetic large-tree fixture:

| Completed phase | Outer body owners | Materialized native body widgets | Widget budget | Dormant bodies | Snapshot widget-class census |
|---|---:|---:|---:|---:|---:|
| Up | 24 | 265 | 320 | 0 | 347 |
| Down | 24 | 259 | 320 | 0 | 340 |
| Reverse | 40 | 216 | 320 | 0 | 299 |
| Idle | 20 | 217 | 320 | 0 | 297 |
| Returned A | 20 | 217 | 320 | 0 | 513 |

Largest captured body has43 native widgets; row extent and source bytes are different resource measures. Returned-A census includes retained peer resources, while this window's materialized body count stays217. These endpoint snapshots do not bound intermediate peaks or the native world beyond capture scope, but they do not support attributing observed25% idle CPU to an enormous resident chat tree at those points.

The same profile still samples foreground readiness/sidebar traversal, native layout/style and backend notification/FieldCodec work. Existing ProfileTrace transitions identify concrete callers, not their CPU shares. Heisenberg has the exact producer/caller findings; frontend/native ownership and backend source reads must be considered together without inventing another semantic store or attributing all work to widget count.

Raw DTO/profiles remain at `/home/ts/.cache/agent-scratch/toad-native-residency-248-20260930-attempt01/capture`; source/runtime/custody hashes and clock limits are pinned in `physical248-installed-residency-comparison-20260930.json`. Do not repeat that accepted physical gate solely to remeasure these same snapshots.
