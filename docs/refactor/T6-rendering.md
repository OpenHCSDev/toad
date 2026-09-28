# T6: The rendering pipeline

**Head audited:** Toad fork `main` at `43e57c9` (#108), with NRA's complete scan at that head (`complete: true`, 79 detectors, none omitted). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** fork. **Step 2,** in parallel with T2. Uses agent-comms' `DeclaredFamily` and `FieldCodec` (TD1). Pattern IDs refer to the refactor-audit skill's catalog.

The protocol between Toad and its own renderer workers is ours at both ends, so its names and shapes change freely.

---

## What is wrong

**A roster of the task family (MEMB-1).** `RENDER_TASK_TYPES` in `render_tasks.py` lists the six task classes (`MarkdownRenderTask`, `PatchRenderTask`, `RichRenderTask`, `TokenRenderTask`, `TranscriptRenderTask`, `ValidateSessionUpdateTask`) that the `RenderTask` family already knows (NRA: `semantic_mirror_without_descent`). `ReusableRenderTask`, the base of four of them, declares no fields and no methods, and no code checks it: a layer that says "reusable" without saying what reuse is.

**Commands carry a kind beside a class that already says it (IMPL-9).** `RenderCommandKind` (`SUBMIT`, `POLL`, `CANCEL`, `ACKNOWLEDGE`, `RELEASE`, `SHUTDOWN`, spelled `"renderer_submit"` and so on) travels with payload classes that already distinguish the cases, and the decoder checks that the two agree:

```python
match kind, payload:
    case RenderCommandKind.SUBMIT, SubmitRender(): ...
    case RenderCommandKind.POLL, PollRender(): ...
```

**Replies are a status switched on by the client (IMPL-2).** `RenderStatus` has eight members (`ACCEPTED`, `BUSY`, `PENDING`, `COMPLETE`, `CANCELLED`, `FAILED`, `UNKNOWN`, `ACKNOWLEDGED`), and `render_zmq.py` decides the client's reaction to each in a chain (`if reply.status is RenderStatus.ACCEPTED: … if reply.status is not RenderStatus.BUSY: … if reply.status is RenderStatus.PENDING: …`), 22 uses across two files.

**The backend is chosen by comparison (IMPL-2).** `RendererBackend` (`LOCAL`, `PERSISTENT`) is resolved with `if backend is RendererBackend.LOCAL: … if backend is not RendererBackend.PERSISTENT: raise`.

**Message categories are grouped by hand (MEMB-2, IMPL-2).** `MessageCategory` (seven members, 33 uses in 11 files) is regrouped wherever grouping matters:

```python
if category in {MessageCategory.USER, MessageCategory.INBOUND}: ...        # agent_activity.py
elif category in {MessageCategory.AGENT, MessageCategory.OUTBOUND}: ...
elif category in {MessageCategory.THINKING, MessageCategory.TOOL}: ...
```

and `agent_response.py` picks `OUTBOUND` or `AGENT` by whether `route is not None`.

**The conversation kind is encoded twice, and misnamed (IDEN-3, IDEN-4).** `HistoryKind` in `channel_preparation.py` is `CHANNEL = "channel"`, `DIRECT = "dm"`, `ALL = "irc"`: the same three strings T5's sidebar rows carry as bare `kind: str`. One concept has two encodings, and two of the enum's names disagree with their values. It is switched on in `channel_preparation.py` and `navigation_preparation.py`.

---

## Target

- **Tasks.** `RenderTask` registers its members; `RENDER_TASK_TYPES` is deleted and anything needing the set derives it. `ReusableRenderTask` either owns what reuse means (for example, the key under which a result is reused) or is deleted: see the required question.
- **Commands.** The payload classes are the family (`SubmitRender`, `PollRender`, `CancelRender`, `AcknowledgeRender`, `ReleaseRender`, `Shutdown`), with derived wire names and `FieldCodec` encoding. `RenderCommandKind` and the paired match are deleted.
- **Replies.** One class per reply, each carrying only its data (`Complete(result)`, `Failed(error)`) and owning the client's reaction:

  ```python
  class RenderReply(DeclaredFamily, affix="Reply"):
      def advance(self, submission: Submission, client: RenderClient) -> Step: ...

  class BusyReply(RenderReply):
      def advance(self, submission, client): return client.retry_later(submission)
  ```

  The chain in `render_zmq.py` becomes `reply.advance(submission, self)`.
- **Backends.** `LocalRenderer` and `PersistentRenderer` each own how they start; T1's backend setting chooses among them as a `ChoiceSetting` over the family.
- **Categories.** Each category is a class; the hand-written groupings become capabilities (`FromPerson` for user and inbound, `FromAgent` for agent and outbound, `AgentWork` for thinking and tool), each owning its presentation in the activity view. Events declare their category; a message's route is typed, so "routed or not" is not a `None` check.
- **Conversation kinds.** One family, `ConversationKind`, with names derived to today's strings (`ChannelConversation` → `channel`, `DmConversation` → `dm`, `IrcConversation` → `irc`), so names and values agree. `HistoryKind` is deleted. **T5 adopts this family** for its sidebar rows, since T6 lands first.

## Required question

**What does "reusable" mean for a render task?** Find where a task's result is reused (a cache, a worker kept warm for the same task type). *Default:* if the reuse depends on the task, `ReusableRenderTask` declares that dependency as a method; if nothing distinguishes reusable tasks in behaviour, it is deleted and its four subclasses derive from `RenderTask` directly.

## Reassigned

`NavigationTarget`, listed under T6 in the index because NRA flags it, is navigation rather than rendering; it belongs to [T5](T5-comms-interface.md), which produces targets from its rows.

## Crossings

- **T1:** the renderer backend setting becomes a `ChoiceSetting` over the backend family.
- **T5:** adopts `ConversationKind`.
- **TL0:** renames `render_zmq.py`'s build-identity check away from "compatibility" wording; that file is T6's during step 2, so T6 does the rename.

## Guards

In `src/toad/`: no `RenderCommandKind`, `RenderStatus`, `RendererBackend` or `HistoryKind`; no comparison of a reply's status; no `RENDER_TASK_TYPES`; no set literal of `MessageCategory` members.

## Tests

- **One family test per family:** each command and reply round-trips through the codec; each reply's reaction against a fake client; each category's presentation.
- **One new-case test:** a test-only reply or task works with one class.
- **Performance gate:** rendering is on every agent's output path, so the existing render pilots run before and after, and nothing gets slower.
- **Delete** tests of the kind-and-payload agreement and of the status chain.

## New-case experiments

- **A reply status.** *Today:* an enum member and a branch in the client's chain, with its data on optional fields. *After:* one class owning its reaction.
- **A message category.** *Today:* an enum member, plus membership in every hand-written grouping that should include it. *After:* one class declaring its capabilities.

## Done when

The five enums and the roster are gone; commands, replies, backends, categories and conversation kinds are families owning their behaviour; the render pilots are no slower; the guards pass.

## Dispatch

> **`toad-t6`:** Complete T6 per `docs/refactor/T6-rendering.md`. Read `00-RULES.md` first. Answer the reuse question from the code before touching `ReusableRenderTask`. Build `ConversationKind` early and announce it on the wire, since T5 adopts it. The render pilots are your performance gate.
