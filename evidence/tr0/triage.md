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
- Integrated current107 T7/T8 and parent229. Prepared package from native-entry-store
  now verifies. Full real Toad→ACP→owner→Pi loopback test passed (5 passing cases
  in declared-native batch); no paid provider request. Private goal fixtures now
  declare the real root/package through current APIs instead of nonprivate ACP.
- Short owned /var/tmp runtime roots fix Unix socket pathname overflow caused by
  nested pytest basetemp paths. Worktrees/logs remain persistent; success fixtures
  are removed after exact attempt processes exit. No native package copy.
- Deleted maintenance_ingress/agent_root_binding plus namespace/stuck-spawn probes
  and their cleanup-only test: these imported a core-test-only synthetic operator
  and internal phase writer absent from installed package. Replaced with one real
  open/refused-child boundary pilot; existing actual cancellation pilot retained.
- Deleted watcher_busy_tabs' tuple-indexed dispatcher/event-injection internals;
  real watcher startup/burst/visibility/peer-close cases remain.
- Deleted raw-Pi executor parts of comms_pilot and project_path/prompt_queue/
  provider_login/thread_controls pilots. Their fabricated argv/stdout executor
  was removed in L0B; no alias or synthetic Pi admission restored. Actual installed
  native test covers ACP attachment/queue/reopen/stopped-owner Start/live channel;
  current goal socket, project resume, UI goal/model/routing and terminal contract
  pilots remain. This does not claim real OAuth provider login was tested.
- Image paste retains responsive mounted capture/private image/text behavior;
  image_attachment_inputs covers ACP image encoding. Removed only fake raw Pi
  send roundtrips, not asserted current clipboard behavior.
- Throbber retains actual paint/geometry/timer behavior; removed borrowed
  Conversation watcher and incomplete fake Sidebar ownership setup.
- In/out replay fixture now records routing through the real route owner; removed
  opt-in annotation switch that relied on deleted prompt-text attribution.
- Recovery rename/sidebar navigation wait for requested identity/destination,
  not a read count or an old screen's idle queue. Hidden diff uses distinct content
  for cancellation so a valid cache hit does not falsely count as a missing render.
