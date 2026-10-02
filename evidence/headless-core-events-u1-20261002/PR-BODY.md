# U1: move application events off Textual

Own the complete U1 core-events surface from all nine documents in the supplied headless UI package. Reuse this finished persistent checkout; no new environment, frontend or benchmark. U2 follows the same ownership boundary; U3 remains coordinated with Kepler338 and Heisenberg339.

Read existing AgentMessage, ACP operational ownership, SessionTracker, Signal subscriptions, application message producers/consumers, DeclaredFamily, MroDispatch and FieldCodec first. Preserve original session/turn/input/permission/terminal authorities. Replace Textual application-event definitions with one UI-independent declared family, wire forms through the existing codec and one generic Textual carrier. Delete per-event carriers and original UI protocol imports in the same caller migration. Widget-local events remain Textual. Live resources remain owned resources, never a copied semantic state or an anonymous serialized object.

Source-first AST inventories declarations, decisions, writes, imports and consumers across production/dependency roots; read semantics and resolve dynamic ambiguities explicitly. Implement the coherent family, then batch proportionate sanity and the affected installed saved-session/native/UI path. No source test is a design method or public readiness claim. Preserve all originals/UNKNOWN and existing package evidence. Parent alone owns default publication.

Current source baseline: Toad main4464a9ed. Published partial implementation below; no installed/readiness claim yet. Existing ACP event payloads include live agent/permission/terminal/output resources, so their existing owner contracts must carry identity/behavior before wire serialization; no second registry or per-event mirror is authorized.

## Published working checkpoint

SessionTracker now owns create/update/close publication through typed core invalidations; App's Textual session Signal, mutable detail tuples and SessionAdmissions' duplicate creation publisher are deleted. Tabs/sidebar read original tracker/projection through one generic Textual carrier and existing MroDispatch. Native scroll restoration belongs to SidebarNavigation rather than the headless data object.

Seven ACP application facts now use that same headless family. Their Textual declarations and all caller references are deleted; status/configuration/client-stop derive the actual original owner instead of carrying copied rendered content or agent fields. Existing AttachedSurfaceBinding owns and closes its subscriber resource; queued work cannot outlive the original subscription. Existing core FieldCodec supplies record wire forms, with no custom codec or per-event Textual mirror. An unused UsageUpdage declaration is also deleted.

The eight existing workspace request members now compose existing Command and CoreEvent and own their operations. SessionAdmissions keeps its original factories and event stream; its duplicate eight-case dispatch roster and the Textual request definitions are deleted. Store/modal results, sidebar/tabs, session navigation and slash publishers use that same stream. MainScreen's competing close handler is deleted. U2 still owns removal of the requests' borrowed frontend service dependencies.

Advertised-command notifications now invalidate the original controller, which the consumer already reads. The ignored copied command list and its Textual declaration are deleted.

The existing ready/failure family now publishes through that same original agent stream. ACP process/session failure and reconnect consumers keep their original behavior; Textual inheritance and all old import references are deleted. Log paths use existing PathText field metadata. The family still borrows native explanation/rendering services, remaining U2 work.

Plan and tool publications now retain their original admitted snapshots in core events. PlanItem owns plain source text; its existing native compose hook creates Content at render time. The duplicate ToolCallUpdate class, ignored second SDK payload and known-call publisher branch are deleted. The external SDK call uses existing FieldRepresentation metadata with the SDK's own JSON contract; FieldCodec still owns record/family forms. The same generic carrier retains native bubbling to both original plan consumers. UserMessage is now an admitted data event without changing saved-history ownership.

The original queued terminal rendering request now belongs to TerminalTool.Projection. Its exact acquired surface/controller/execution guards remain; the ACP declaration is deleted. Existing AttachedSurfaceBinding owns its native projection behavior, while the absent-surface hook acquires no rendering work. No terminal snapshot or custody registry is added.

Source/AST and ownership reasoning are in SOURCE.md and before-ast.json (276 production +389 test modules,0 omissions; lexical name collisions qualified). This is a working partial U1 implementation. Output/permissions/Comms and other application intents/Signals remain under the full draft scope. Final proportionate sanity and installed affected path follow the coherent source batch; no installed/U1-ready claim yet.
