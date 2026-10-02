# U1: move application events off Textual

Own the complete U1 core-events surface from all nine documents in the supplied headless UI package. Reuse this finished persistent checkout; no new environment, frontend or benchmark. U2 follows the same ownership boundary; U3 remains coordinated with Kepler338 and Heisenberg339.

Read existing AgentMessage, ACP operational ownership, SessionTracker, Signal subscriptions, application message producers/consumers, DeclaredFamily, MroDispatch and FieldCodec first. Preserve original session/turn/input/permission/terminal authorities. Replace Textual application-event definitions with one UI-independent declared family, wire forms through the existing codec and one generic Textual carrier. Delete per-event carriers and original UI protocol imports in the same caller migration. Widget-local events remain Textual. Live resources remain owned resources, never a copied semantic state or an anonymous serialized object.

Source-first AST inventories declarations, decisions, writes, imports and consumers across production/dependency roots; read semantics and resolve dynamic ambiguities explicitly. Implement the coherent family, then batch proportionate sanity and the affected installed saved-session/native/UI path. No source test is a design method or public readiness claim. Preserve all originals/UNKNOWN and existing package evidence. Parent alone owns default publication.

Current source baseline: Toad main4464a9ed. No implementation/readiness claim yet. Existing ACP event payloads include live agent/permission/terminal/output resources, so their existing owner contracts must carry identity/behavior before wire serialization; no second registry or per-event mirror is authorized.
