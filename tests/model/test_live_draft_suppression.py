from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent_comms.execution.transcript_sources import DraftFold
from agent_comms.execution.turn_item import NativeItemId, NativeTurnId
from agent_comms.nominal.field_codec import ThreadLookup
from agent_comms.transcript.transcript_drafts import NoDraft
from agent_comms.transcript.transcript_events import AssistantTranscript

from toad.client.committed_presentation import covers_live_draft
from toad.commit_claims import LiveResponsePresentation, SnapshotPresentation
from toad.live_output import LiveOutput, ResponseStream, ThoughtStream
from toad.qt.live_turn import QtResponseBlock, QtThoughtBlock, QtUserInputBlock
from toad.transcript_publication import CanonicalSourcePublication
from toad.turn_presentation import LiveBlock, TurnPresentation
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought


class _FakeBlock(LiveBlock):
    def __init__(self, text: str) -> None:
        self.text = text
        self.finished = False
        self.removed = False

    @property
    def loading(self) -> bool:
        return not self.text.strip()

    async def append_fragment(self, fragment: str) -> None:
        self.text += fragment

    async def finish_stream(self) -> None:
        self.finished = True

    async def remove(self) -> None:
        self.removed = True


class _FakeResponseBlock(LiveResponsePresentation, _FakeBlock):
    pass


class _FakeThoughtBlock(SnapshotPresentation, _FakeBlock):
    pass


class _FakeTurnView(TurnPresentation):
    def __init__(self) -> None:
        self.blocks: list[LiveBlock] = []
        self.cleared_drafts = 0

    @property
    def shows_live_output(self) -> bool:
        return True

    def after_live_output(self, finish) -> None:
        pass

    async def present_user_input(self, text: str) -> None:
        pass

    def response_block(self, fragment: str, delivery) -> LiveBlock:
        return _FakeResponseBlock(fragment)

    def thought_block(self, fragment: str) -> LiveBlock:
        return _FakeThoughtBlock(fragment)

    async def show_live_block(self, block: LiveBlock, stream) -> None:
        self.blocks.append(block)

    def clear_draft(self) -> None:
        self.cleared_drafts += 1

    async def present_error_note(self, message: str, details: str) -> None:
        pass

    async def present_help_note(self, markdown: str) -> None:
        pass

    async def present_log_link(self, markdown: str) -> None:
        pass


def _sample_draft() -> DraftFold:
    turn_id = NativeTurnId("turn-1")
    item_id = NativeItemId("item-1")
    return DraftFold(
        thread=ThreadLookup("a" * 32),
        turn_id=turn_id,
        item_id=item_id,
        events=(AssistantTranscript("streaming reply", position=item_id, timestamp=1.0),),
    )


def test_covers_live_draft_marks_only_live_response_presentations() -> None:
    assert covers_live_draft(AgentResponse("hi"))
    assert covers_live_draft(QtResponseBlock(None, "hi"))  # type: ignore[arg-type]
    assert not covers_live_draft(AgentThought("hmm"))
    assert not covers_live_draft(QtThoughtBlock(None, "hmm"))  # type: ignore[arg-type]
    assert not covers_live_draft(QtUserInputBlock(None, "yo"))  # type: ignore[arg-type]
    assert not covers_live_draft(object())


def test_canonical_source_publication_suppresses_draft_while_live_response_shown() -> None:
    shown: list[object] = []

    class _FakeView:
        def __init__(self, blocks: tuple[object, ...]) -> None:
            self.live_blocks = blocks

        def show_draft(self, draft, identity) -> None:
            shown.append(draft)

    draft = _sample_draft()
    pub = object.__new__(CanonicalSourcePublication)

    # CLI / observation-only or thought-only view: draft is forwarded intact.
    object.__setattr__(pub, "binding", SimpleNamespace(view=_FakeView((_FakeThoughtBlock("thinking"),))))
    pub.show_draft(draft, identity=None)  # type: ignore[arg-type]
    assert shown[-1] == draft

    # Live ACP response already mounted: draft is suppressed to NoDraft().
    object.__setattr__(pub, "binding", SimpleNamespace(view=_FakeView((_FakeResponseBlock("streaming"),))))
    pub.show_draft(draft, identity=None)  # type: ignore[arg-type]
    assert isinstance(shown[-1], NoDraft)


def test_live_output_response_stream_clears_draft_on_open_and_thought_does_not() -> None:
    async def run() -> None:
        view = _FakeTurnView()
        output = LiveOutput(view)

        await output.append(ThoughtStream(), "thinking...")
        assert view.cleared_drafts == 0

        await output.append(ResponseStream(), "hello ")
        assert view.cleared_drafts == 1

        # Subsequent fragments on the same ResponseStream do not re-clear.
        await output.append(ResponseStream(), "world")
        assert view.cleared_drafts == 1

    asyncio.run(run())
