# TR0 checkpoint — packaged owner and collector ready; remaining failures owned

Core254 e542fe82 (merged-main229 reconciled). Toad117, based current107540a602;
pyproject/committed uv.lock pins core254, Textual16ede. Parent owns deployment.
Newest instruction: do not hold these source changes for a full-suite/CI gate.

Completed:
- One installed Comms ratchet; no copied script/manual pilot roster.
- One derived collector runs each actual script entrypoint once, including explicit
  unittest-script selection. No per-pilot adapter list. 3 collector/deletion guards
  pass; actual packaged console has 11 passing real Git tests.
- Installed packages only, private roots, bounded child execution, exact attempt
  identity cleanup for detached workers. Short disposable /var/tmp runtime paths
  respect Unix socket limits; worktrees and failure logs stay persistent ~/wt.
  One configurable165sec attempt budget, no retries/skips. Successful roots cleaned.
- Manual-only workflows; no required checks or branch protection changes.
- Current107 T7/T8 integrated; retained failures and deletion rationale in triage.md.
- Confirmed product fix: narrow preview warning clipped in pane; existing rendered
  assertion passes after wrapping and removing redundant filename.

Evidence, without claiming a green whole suite:
- First full installed pass:215passed49failed,73subtests,640.58s. Preserved XML/logs.
- Current107/core229 failed-case rerun:14passed29failed,228.11s; then concrete fixes.
- Real installed Toad→ACP→owner→Pi loopback pilot passes current native package:
  queued input exactly once, cold attach/native reopen, DM and channel feedback.
  No paid provider; reused native-session-entry-store package, no duplicate install.
- Current goal socket/edit/pause/set/standby, saved context, project resume, routing,
  responsive clipboard, invalid/open maintenance, throbber, renderer reuse/UI,
  read-only old marker/history, collector and file-preview cases pass in bounded
  batches. See current-goals/fixture-boundaries/current-ui/declared-native receipts.
- Projected history8000/bidirectional budget passes in follow.log (1pass2fail,
 90.81s); original90sec runner was too small. No behavior assertion weakened.

Concrete followup remains owned by Pascal, not unassigned or a merge gate:
1. thread_activation first resumed paint shows stale viewport before latest text.
   An attempted follow/layout correction did not meet the full frame assertion;
   it is EXCLUDED from source candidate, retained first-frame-incomplete.patch.
2. relationship_poll_reflow's zero-paint fixture includes deliberately animated
   busy rows; idle-source correction needs final diagnosis (not a product verdict).
3. session_sort's busy phase needs valid live turn witnesses for both rows;
   no restoring activity-only busy fiction. Current failure retained.
4. Remaining derived PTY/visual/operator scripts need classification; existing
   headless UI subset and native loopback are established, not full terminal suite.
Full plan triage continues in this ownership. No repeated paid/provider proof or
CI wait required. All deletion/failure evidence retained; no live mutations.
