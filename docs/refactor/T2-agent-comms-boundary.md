# T2: The ACP and agent-comms boundary

**Heads audited:** Toad fork `main` at `43e57c9` (#108); agent-comms `main` at `bf68bbb` (#230). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** mostly fork. **Step 2.** Spans both repositories: one agent, two PRs, merged and installed together. Uses agent-comms' `DeclaredFamily`, `FieldCodec`, `MroDispatch`, the compaction lifecycle states (#186) and `ThreadIncarnation` (TD1). Pattern IDs refer to the refactor-audit skill's catalog.

---

## The boundary

Toad receives two kinds of data from an agent:

- **The ACP specification's own updates** (`agent_message_chunk`, `tool_call`, `plan`, …). The format is external. Upstream models it as `TypedDict`s in `acp/protocol.py` and matches the `sessionUpdate` discriminator once, in `_apply_session_update`. That is the right shape at an external boundary, and it stays.
- **agent-comms' extension**, carried in `_meta.agentComms`: queue state, input delivery, goals, compaction, activity, coordination, the private native cursor. **Both ends are ours**, so its format changes freely, in lockstep. This surface is about the extension.

---

## What is wrong

**The extension is a protocol nobody declares (IMPL-1, IMPL-9).** It is a bag of optional keys in which **which keys are present encodes what happened**:

```python
state = metadata["agentComms"]
if "queueState" in state: ...
if "inputStarted" in state and ("inputId" in started and isinstance(started.get("text"), str)): ...
if "inputDisposition" in state or state.get("inputDeliveryChanged") is True: ...
failed = state.get("inputFailed")
if isinstance(failed, dict) and isinstance(failed.get("text"), str): ...
compaction = state.get("compaction")
if isinstance(compaction, dict) and compaction.get("phase") in {"start", "progress", "end", "abort"}: ...
```

On the producing side, the keys are spelled in at least six agent-comms modules (`transcript_updates.py`, `input_drain.py`, `session_lifecycle.py`, `runtime.py`, `acp.py`, `native_source_cursor.py`). Nothing states the protocol; the two repositories agree by coincidence of spelling.

**Wire keys are copied field by field into UI messages (MEMB-5).** `_publish_coordination_metadata` reads twelve keys raw and stores them as attributes of `Agent` itself (`self._coordination_owner_pid`, `self.server_titles`, …); `_post_coordination_update` then copies those attributes into `messages.CoordinationUpdate(...)`. The compaction branch copies its keys into `messages.CompactionUpdate(...)` directly. These classes are Textual messages posted to the interface, not decoders: each restates the wire's fields under new names. (An earlier note in this package called this "bypassing an existing class"; it is a hand mapping, in two hops.)

**Capability flags between our own components (TIME-4).** agent-comms advertises `turnLifecycle`, `autoTitle`, `promptQueue` and `imagePrompts`, and Toad checks each (`self.supports_prompt_queue = coordination.get("promptQueue") is True`). The two are pinned and installed together, so Toad knows what agent-comms supports; the flags exist only to tolerate version skew. Missing fields also become invented display text: `coordination.get("persistence", "shared on-disk wire")`, `coordination.get("transport", "per-session stdio ACP")`, so absent data is shown as a made-up description.

**Hand decoders and a second authority (BOUND-1, BOUND-3).** `private_native_cursor.py::parse_cursor` is an 80-line hand decoder returning `CursorEnvelope | None`. `queue_view.py` reads 13 raw keys, and its `QueueReducer` rebuilds queue state from events, while the queue belongs to agent-comms.

**Retired vocabulary on both sides (TIME-1).** agent-comms replaced epochs with `ThreadIncarnation` and generations; Toad still uses epoch names 44 times (`owner_epoch` 30, `epoch` 9, `owner_admission_epoch` 2, `ownerEpoch` 2, `quarantine_newer_epoch` 1), and agent-comms still emits `ownerEpoch` from `input_drain.py` and `acp.py`.

**Attribute probes across the boundary (BOUND-7):** `session_id` 5, `wire_root` 3, `session_pk` 3, `project_path` 3, `_queue_view` 3, `_coordination_root` 3, `get_input_delivery` 2. Widgets reach into the app's private attributes for coordination facts no one owns.

**The agent class absorbs it all (AGENT-4, IMPL-8).** `Agent` grew from 773 to 1,886 lines; `_apply_session_update` is 285 lines.

Upstream also switches on `agent_data`'s type in `_run_agent` (four `isinstance` checks, IMPL-3); it is decoded once into a record here too.

---

## Target

### agent-comms declares the extension once

```python
# agent_comms/acp_extension.py
class AgentCommsUpdate(DeclaredFamily):
    """One fact agent-comms reports to an ACP client. Encoded by FieldCodec with its derived kind."""

@dataclass(frozen=True)
class InputStarted(AgentCommsUpdate):
    input_id: InputId
    text: str

@dataclass(frozen=True)
class InputFailed(AgentCommsUpdate):
    text: str
    reason: DeliveryFailure            # a family, not a free string with a default

@dataclass(frozen=True)
class CompactionChanged(AgentCommsUpdate):
    state: CompactionState             # the lifecycle states from #186, not phase strings

@dataclass(frozen=True)
class CoordinationChanged(AgentCommsUpdate):
    thread: ThreadIncarnation          # generations, never epochs
    wire_root: Path
    ...

# also: QueueChanged, InputDelivery, GoalChanged, ActivityChanged, CursorAdvanced, McpClientReceipt
```

- Each member is one fact; the wire carries a list of them under `_meta.agentComms.updates`, each with its derived kind name.
- **Every producer module constructs records**; no dict with these keys remains anywhere in agent-comms.
- `CursorAdvanced` carries the cursor envelope as a record, so `parse_cursor` has nothing left to do.

### Toad decodes into the same classes, once

```python
# the single boundary, in the ACP agent
for update in AgentCommsUpdate.decode_all(meta):      # FieldCodec, strict: unknown kinds or keys fail here
    self.comms.handle(update)

class CommsUpdateConsumer(MroDispatch):
    @handles(InputFailed)
    def show_failed(self, update: InputFailed) -> None: ...
    @handles(CompactionChanged)
    def show_compaction(self, update: CompactionChanged) -> None: ...
```

- Toad imports agent-comms' records; it declares no copy of the protocol.
- **UI messages carry the record** (`CommsUpdated(update)`), so the field-copying message classes (`CoordinationUpdate`, `CompactionUpdate` and their siblings built from wire fields) are deleted.
- **One owner for coordination facts:** the latest `CoordinationChanged` lives on one typed attribute of the app; every name probe is deleted.
- `_apply_session_update` keeps only the ACP specification's discriminator match and hands `_meta` to the decoder. The extension handling leaves `Agent`.
- **The capability flags are deleted** on both sides; the features they gated are simply on. Fields decode strictly, so a missing one fails at the boundary instead of rendering invented text.
- All 44 epoch names become generation vocabulary from `ThreadIncarnation` and `TurnIdentity`, on both sides, in the same change.

### Lockstep

One agent-comms PR and one Toad PR, merged together and installed at one cutover. There is no period in which either side accepts both formats. The protocol is live state only; nothing persisted changes.

---

## Required questions (answer from the code before building)

1. **Does agent-comms already hold the queue projection that `QueueReducer` rebuilds?** *Default:* yes; agent-comms sends it in `QueueChanged`, and `QueueReducer` and its event types are deleted. If Toad's reducer computes something agent-comms does not, that computation moves to agent-comms.
2. **Does one ACP update ever need to carry several facts?** *Default:* yes, hence a list; if every producer sends exactly one, the wire carries one record.

---

## Guards

- **Toad:** no `_meta` or `agentComms` access outside the decoder; no epoch names; no `getattr` or `hasattr` naming coordination attributes; no Textual message class whose fields restate an extension record.
- **agent-comms:** no dict literal containing an extension key outside `acp_extension.py`; no `ownerEpoch`; no capability flags advertised to Toad.

## Tests

- **One family test in agent-comms:** every `AgentCommsUpdate` member encodes and decodes to itself. Both ends use the same classes, so this covers the protocol; no golden files, since the format is ours.
- **One new-case test:** a test-only update travels from a producer to a Toad handler with one class and one handler.
- **One Toad pilot** feeding recorded payloads from the new producer through the real consumer.
- **Delete** tests of `parse_cursor`, `QueueReducer` (per question 1), the field-copying messages, and the key probing.

## New-case experiment

**A new fact agent-comms reports.** *Today:* a key in some producer module's dict, a probe in `_apply_session_update`, fields on a UI message, sometimes a reducer case: three or four edits across two repositories, none checked. *After:* one record class in agent-comms and one handler in Toad; a misspelling fails at import.

## Done when

The extension is declared only in `acp_extension.py`; agent-comms constructs records and Toad decodes them with no copy of the protocol; the hand decoders, the field-copying messages and the name probes are gone; no epoch vocabulary remains on either side; the guards pass in both repositories.

## Dispatch

> **`t2-boundary`:** Complete T2 per `docs/refactor/T2-agent-comms-boundary.md` (Toad) with its agent-comms half in the same change. Read both repositories' `00-RULES.md` first. Declare the extension once in agent-comms, convert every producer, and make Toad decode into the same classes; answer the two required questions from the code first. One PR per repository, merged and installed together; neither side ever accepts both formats. Crosses T5 (the comms interface consumes coordination facts) and T3 (both touch `Conversation`): T2 lands first.
