# PR245 resource custody and retained physical profile closure

**Production lines deleted by this contribution: 0.** Read-only source/profile contribution from Kepler to Heisenberg, the sole PR245 production and integration owner. No new capture, provider call, native input, public mutation or production patch. Source inspected: `1de10e3f910a649b152120e866f30c832737a885` in the existing foreground-layout worktree. The JSON companion pins source bytes, retained raw traces and custody evidence.

## What the existing source check establishes

The latest `body-cost-245-custody-final` check holds the real accepted history's next fragment Mount **before** its viewport registration. Original native page children then contain six fragment bodies while registered viewport roots contain five. `HistoryWindow.history_lock` and its native publication fence remain held, and `ViewportPresentation.prepare()` refuses paint. After release, observation under the same original history lock gives eight roots and eight matching fragment resources.

This demonstrates an intermediate native Mount boundary. Settling only `DocumentViewport._pending/_running` and visible-body readiness does not settle independent source/page work. The original observer must use the existing history admission boundary when asserting accepted membership. Do not weaken root equality or add another completion bit, root list or source registry.

The earlier intermittent assertion had no failing resource identities. Its exact cause remains unestablished; a deterministic intermediate mismatch explains a real observer risk without retroactively identifying that earlier failure. Original failed artifacts remain protected. Source checks are not installed physical acceptance.

| Original declaration/consumer | Required relation |
|---|---|
| `TranscriptHistory.fragment_views`, transcript_history.py:408 | Native fragment children of the currently owned pages |
| `TranscriptFragmentView.on_mount/on_unmount`, :187/:193 | Existing viewport registration follows native Mount/Unmount |
| `DocumentViewport.body_roots`, viewport_body.py:251 | Roots derived from original Window children and current registered owners |
| `SnapshotPublication.publish`, transcript_publication.py:91 | Admission and retirement occur under the original history lock/publication fence |
| `TranscriptPageView.extend/update_fragments`, transcript_history.py:340/:360 | Mount awaits may expose intermediate native children before registration completes |

No second semantic authority is required. The existing resource capability owns admission and reconstruction. Apply the NRA IMPL-12 discipline to resource-cost reuse: shared `MeasuredViewportBody` behavior extends its existing `BodyMeasurement`, rather than copying cost decisions into consumers.

## Body-cost invalidation is conservative, not membership-only

PR245 keys existing measured native cost with the original `NodeList._updates`. Textual `_node_list.py:74` propagates descendant updates to ancestors. `DOMNode.id` assignment and `set_display_constraint` also update that revision; it is not exclusively a child-membership counter.

The exact Textual2e `set_display_constraint` guard at dom.py:988 returns when the requested reason is already allowed/blocked. Unchanged calls neither advance the token nor refresh layout. Changed constraints can conservatively invalidate the measured cost even when another constraint keeps effective display unchanged. This is safe over-invalidation; it does not justify an invented narrower epoch or another resource registry.

Latest source receipt: 555 native descendants, 24 body roots, zero descendant walks in profiled selection/admission, selection approximately 0.500→0.0068 ms and admission 0.054 ms. These are source-check timings, **not** a whole-workflow CPU or key-to-paint claim.

## Concrete remaining consumers in the actual retained recording

Existing actual PR242 capture: original A41MB/B13MB saved history, physical held Up/Down/reverse, End/idle and A/B/A draft/Undo. No replacement capture was made. Both release02 and PR242 passed sixteen native journey checks; their CPU evidence did not establish an overall reduction. The retained ProfileTrace query selects exact functions and preserves complete original call chains.

| Nominal recording marker | Concrete observed original chain | Current production lead |
|---|---|---|
| Down 30.728 s | SidebarObservation.read→SidebarProjection.publish→rebuild→SidebarNavigation.mode_changed→DOMQuery→walk_children | Rebuild forces mode reconciliation and queries every ThreadRow |
| Down 31.751 s | Screen idle callbacks→TranscriptHistory._check_edges→walk_children | Every visible pager edge check inspects descendant Mount completion |
| Down 34.788 s | Workspace compositor preparation→ViewportPresentation.prepare→visible_bodies_ready→TranscriptFragmentView.body_ready→walk_children | Recursive body readiness still runs outside retained widget-cost reuse |
| Idle 55.603 s | SidebarObservation.read→publish→rebuild→mode_changed→DOMQuery→walk_children | Periodic source publication still reaches the whole row query |
| Return A 73.084 s | Native message callbacks→mode_changed→DOMQuery→walk_children | Mode reconciliation also reaches this query on retained tab return |

Current `SidebarProjection.rebuild` at :151 calls `mode_changed(force=True)`. `mode_changed` at sidebar_navigation.py:154 queries the entire subtree. Original row custody/order lives in each group's `member_container.children`; use that declaration owner if optimizing this consumer, without another row index. **Correction from the later PR249 source trace:** `ChannelGroup.member_rows` is a stored tuple assigned after awaiting reconciliation, not a derived native-child property. It can still hold old row references while reconciliation yields. Reusing that tuple unchanged would preserve a second ordering instead of deriving native custody. Ordinary `mode_changed` calls already skip unchanged `(mode_name, target)` and inactive screens. A sampled forced walk alone does not prove unnecessary rebuild: changed wire/status/unread content may legitimately require publication.

Other source walk consumers remain outside the body-cost checkpoint: `TranscriptHistory.widget_count` at :494, `retained_source_bytes` at :499, `_extend_and_trim` at :851/:881, and fragment nested-body readiness at :198. These are concrete caller leads, not permission to replace authoritative readiness or native custody with mirrored booleans. Any closure belongs to the existing history/viewport/row declaration owner and must preserve its native lifecycle.

## Measurement limits and next action

The query reports changed Chrome stack groups, **not** samples, call counts, durations or CPU attribution. Kernel per-process counters remain CPU authority. The original profiler-origin bracket supplies nominal alignment only; no first-FFmpeg-frame timestamp was recorded, so it cannot prove absolute frame correlation or a sub-50 ms result. Retain the established ProfileTrace/recorder timing boundaries; there is no NativeProxy clock or owner.

Heisenberg has the exact remaining caller chains and owns the next single affected installed physical gate after the PR245 source checkpoint. Compare that candidate's retained warm history, physical fast/reverse/idle scroll and CPU evidence through existing tools. Keep these leads available for subsequent production changes without repeating already accepted captures or blocking parent release work. Full CPU/focus/warm-cache/TC1/T9/growing-End scope remains open.

Raw preserved query: `/home/ts/.cache/agent-scratch/kepler242-physical-review-20260930/resource-custody-stack-review.json`. Original physical/profile capture: `/home/ts/.cache/agent-scratch/toad-history-projection-242-20260930-attempt01/capture`. Source custody proof: `/home/ts/wt/toad-workspace-foreground-layout-continuation-20260930/.artifacts/body-cost-245-custody-final`. The companion JSON retains hashes and query results, not a runtime cache or production state store.
