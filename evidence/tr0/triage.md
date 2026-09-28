# Concrete triage (updated during first complete installed run)

- Collector correction: user namespaces changed inode UID interpretation and
  failed valid private-root authority checks. Replaced with existing BoundedRun
  and exact ProcessIdentity retirement of only fixture-root processes. Failed
  attempt: 27failed/38passed before stopping; not a suite result.
- Deleted auto_compaction_visibility_pilot: probes retired raw backend event
  mappings/_emit_event transport, not current typed native boundary. Current
  midturn/progress UI tests and native core contract remain.
- Deleted current_delivery_owner_pilot and input_delivery_owner_pilot: reference
  removed queued_delivery_owner/backend_inboxes and AcpDeliveryCursors/old socket
  compatibility. Current queue-view/actual-native pilots protect retained behavior.
- Deleted channel_marker_notice_pilot: explicitly tests retired pre-ledger marker
  conversion (_marker_key/read_markers.json). No migration path to restore.
- Deleted the two parameterized inode/body replacement cases inside
  channel_history_reader_pilot: require accepting tampered committed private wire;
  current canonical checkpoint correctly refuses this. Other scope/lease/history
  reader behavior retained; whole-root rebind tests remain.
- Repaired channel_retirement: seed through real publication before declaring
  read-only historical audience, instead of fabricating uncommitted wire frames.
- Repaired default_route_private_user: remove deleted background scheduler patch;
  inject failure on append open only, after real reservation. Read-preflight
  failure is correctly safe and must not be falsely asserted as UNKNOWN.
- Repaired goal_standby_history readiness: wait on current roster acceptance before
  asserting known-peer links; no fixed delay/retry and assertion unchanged.
- Concrete production file-preview regression: filename-prefixed warning was
  horizontally clipped in narrow preview pane. Notice gets available width and
  omits redundant filename (already shown in header); full warning remains visible.
- Optional persistent-renderer cases need the declared extra; use installed
  `uv sync --locked --all-extras --no-editable`, not missing-dependency skips.
- Color pilots inherited NO_COLOR=1/TERM=dumb from the automation shell. Collector
  now declares a truecolor terminal and removes NO_COLOR for real UI color checks.
- Moved watcher_archived_ui and watcher_project_shutdown to tools/performance:
  operator diagnostics require WATCHER_ACCEPTANCE_STAGE/WATCHER_ARCHIVED_WIRE or
  an actual existing project, not reproducible unattended fixture inputs.
- Moved navigation_allocation and real_history_scroll_latency to tools/performance:
  workload/profile reports with output arguments/latency measurements; the
  underlying correctness/many-tab workload pilots stay collected.
