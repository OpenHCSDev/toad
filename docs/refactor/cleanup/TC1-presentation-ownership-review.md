# PR213 presentation ownership review

Reviewed inherited production406253bd and normal main43949 union2d204ae8. PR213
now adds owned-resource close and canonical reader geometry changes. Authoritative refactor-audit.skill SKILL.md,
patterns/README.md, IDEN-1/3/5, IMPL-1/4/10/12/14 and TIME-1 through9 reread from
the archive. Whole202/208 now merged main43949 and parent activated that pair;
the213 follow fix remains a source candidate. Keep those readiness boundaries.

## Owner and consumer trace

| Relation | Actual owner and consumers | Verdict |
|---|---|---|
| Selected workspace identity/lifetime | WorkspaceSessions.source; App.selected_session/selected_mode, SessionView.is_current, WorkspaceScreen command/root/focus delegate | One canonical selected source. Detached/loading/shown/parked behavior stays on the family; native resource admission is distinct from selection. IDEN-3/IMPL-10 |
| Retained native resources | OperationalSessionPresentation.widget, NativeSessionSurface admission/eviction; DocumentViewport and TabOrder bound inactive resources | Actual widget trees and renderer resources are allowed. Agent/shell/watcher references retain the same operational objects during eviction, not independently reconstructed model state. Remaining optional resource admission probes still require TC1 closure |
| Editor and reader resources | SessionViewState.capture/restore; NativeSessionSurface._evict/activate | Actual TextAreaState document/history is retained, not a competing editable flag. ReaderPosition is layout intent. Visible filter/shell preferences and pending initial input require explicit ownership review; not all snapshot fields are automatically rendering resources |
| Context/turn/goal first-frame projection | NativeSessionSurface.activate writes Conversation.status, calls turns.bind and goal_observation.refresh; Conversation.watch_agent/present_retained_native_session also write status | Remaining IDEN-3/IMPL-12 crossing. Arendt owns canonical status/turn/goal publication. Request one inherited projection/invalidation contract before deleting these consumers; do not replace them with another ready/busy flag |
| Pending initial input | MainScreen._initial_prompt -> _make_conversation; Conversation._initial_prompt consumed by watch_agent_ready; SessionViewState captures it for eviction | MainScreen keeps the original string after creation. This is a genuine duplicate input value, even though the eviction snapshot currently prevents repeat submission. Parent canonical input owner must receive the entire creation/consumption/eviction relation; no last-input mirror or local replay workaround |
| Saved history reader publication | HistoryWindow native movement watcher; SnapshotPublication.publish; TranscriptPresentation.reveal_retained/refresh_revealed/painted; CheckpointPlan/ReaderPosition own intent |213 proves positive geometry can turn offset into follow without input. Geometry checks no longer choose intent; native downward movement and explicit End do. Snapshot's unconditional anchor writer and prepare_reader boolean consumer are deleted; source/frontier validation stays Schrodinger. Existing native restoration transaction owns compensation, with no added reader flag/cache |
| Sidebar actions/geometry | SidebarPlacementAction/SidebarShift declaration behavior; SideBar dispatch delegates; WorkspaceChrome resolves actual applying member | No competing placement registry. Members derive controls. A new placement action requires one declaration, zero consumer switch/roster edits. Spatial left/right coordinates remain an external UI geometry boundary, not backend semantic state |

## Deletion and closure

Whole202 versus main209 deletes418 production lines and adds577 across19files.
Those are checkpoint counts, not new213 deletion. Transfer fragment identity,
shared Conversation reset/rebind and shelf/page/body transfer consumers are gone
in406. Search confirms no FragmentPresentationIdentity, fragment identity getter,
is_untouched or park_body in this integrated source. Maincd791 still has the
207-restored park_body; Kepler208's whole202 union removes it normally. Do not
patch that older consumer and keep a second lifetime mechanism beside the union.

ACPAgentPresentation.restore_saved_history remains live: it delegates native
history restoration only when the actual route owns a transcript; Local's
contract leaves its mounted tree intact. Deleting this capability would break
generic SDK versus native source correctness. It is not version negotiation or
a format fallback (TIME-4). No codecs or compatibility aliases were added.

New-case check: a workspace state implements the existing owner contract;
WorkspaceScreen/App consumers do not gain an alternative-state switch. A new
render demand belongs to DirectionalPreparation and uses the existing worker
pool/cache. Source operation validation is inherited from Schrodinger, never
copied into demand state. These checks do not certify the unfinished eight-file
TC1 closure or canonical semantic projection crossing.

## Actual acceptance boundary

406 production matches the installed993 wheel's266 Python files; the current
Coreab/Textual412/native7817 continuous native/UI path passed five returns and
sixteen completed destination frames with zero misses. The integrated208cd445
candidate subsequently failed later-frame reader equality, then passed with the
same production. Parent shipped that checkpoint with intermittent risk disclosed.
Identity hits and correct first-frame markers do not close it. Preserve both
receipts; native candidate213 A/B/A still needs confirmation. Installed main43949
fails the complete geometry/key counterexample; source213 on the same pair passes.
See evidence/reader-geometry for all completed frames and the bounded two-file
per-function/per-file dispatch ratchet. Large physical video/CPU, active/post-cancel
editor deletion/arrows and source-restart same-open-view recovery remain open.
