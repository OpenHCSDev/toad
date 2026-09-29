# TC1 workspace source and layout checkpoint

PR202 owns TC1 workspace/presentation lifetime and the assigned T9/T4 workspace
crossings. Patterns: IDEN-3, IMPL-10, IMPL-14; dead transfer path TIME-6.

WorkspaceSessions owns detached, loading, shown and parked source custody.
WorkspaceScreen asks it for commands, coordination root and focus; SessionView
asks it for current ownership. Store retirement parks that source. Returning to
the same session reactivates it rather than skipping on an old selected pointer.
Only fully shown sources can satisfy selection immediately; loading sources
still own their presentation while preparation completes.

WorkspaceScreen owns a typed measured layout record with one native Textual
snapshot: size, stylesheet revision, mount/stack and invalidation facts. Removed
three navigation flags and seventeen long-condition terms. Native Textual
invalidation remains authoritative; this is neither a view model nor a paint
bitmap/cache. Resize, styles and preparation changes invalidate that proof.

Existing physical controls journey passed exit0 under a 60s bound with no provider:
move/swap/float, width, channel open, resize, return and store/same-session resume.
Command: PYTHONPATH=src:tests TMPDIR=.artifacts/workspace-source-layout
.artifacts/sidebar-geometry-package/runtime/bin/python -B -u
tests/sidebar_layout_controls_pilot.py. Physical controls stayed actual clicks;
store/resume exercises the public application workflow.

Per-file and per-function dispatch/arms ratchets passed against preceding HEAD;
WorkspaceScreen chain terms 17 to 0 and NoneIdentity 11 to 8. App NoneIdentity
15 to 14, WorkspaceSessions 1 to 0. These are checkpoint counts, not TC1 closure.
The eight-file pre129 baseline remains NoneIdentity4/ForeignAbsenceProbe11;
remaining lifecycle/publication/source/terminal probes keep TC1 open.

Parent owns Conversation activity/status/input/cancel and backend projection.
Kepler owns TC2 ACP/model/tool consumers. Schrodinger owns T5 receipts/history;
only explicit prior lifecycle and deferred-reader handoffs belong to PR202.
The Conversation untouched/18-field pool probe was removed with the shared
transfer optimization; there is no remaining consumer needing that probe.

This source/layout edit has provider-free UI proof; installed native acceptance
above covers the preceding 887ad457 checkpoint. Current-main integration and
large-history recorded scrolling/CPU plus bounded16/32/64 acceptance remain open.
