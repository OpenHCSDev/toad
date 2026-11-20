"""Qt's live turn output: the shared turn code's blocks, drawn as history rows.

Textual mounts an `AgentResponse` or `AgentThought` widget for each live stream. Qt draws
the same block as a transcript fragment after the saved history (as it draws a CLI draft),
so it uses the row delegate, the sticky header and the reader's place like every other
row. A block's fragment is rebuilt from its text as fragments stream in; its `revision`
keys the row cache. Once the block finishes, the saved history that commits the same
output takes over, and the window drops the finished block when its pages change.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.transcript.transcript_events import (
    AgentTextTranscript,
    ThinkingTranscript,
    TranscriptEvent,
    UserTranscript,
)

from toad.client.fragments import GrowsInPlace
from toad.client.transcript_fragments import TranscriptFragment
from toad.turn_presentation import LiveBlock

if TYPE_CHECKING:
    from toad.qt.history import QtHistoryWindow

_serials = itertools.count(1)


@dataclass(kw_only=True)
class QtLiveFragment(GrowsInPlace, TranscriptFragment):
    """A live block's row: one transcript event that grows in place."""


class QtLiveBlock(LiveBlock):
    """One live block in a Qt history window. Its position is negative, so its row key can
    never meet a saved event's."""

    event_kind: type[TranscriptEvent] = AgentTextTranscript

    def __init__(self, window: QtHistoryWindow, text: str) -> None:
        self.window = window
        self.text = text
        self.source_claim: object = None
        self.finished = False
        self.revision = 0
        self.position = -next(_serials)
        self.timestamp = time.time()

    @property
    def loading(self) -> bool:
        return not self.text.strip()

    def fragment(self) -> QtLiveFragment:
        event = self.event_kind(self.text, position=self.position, timestamp=self.timestamp)
        return QtLiveFragment(events=(event,), live_revision=self.revision)

    async def append_fragment(self, fragment: str) -> None:
        self.text += fragment
        self.revision += 1
        self.window.live_changed()

    async def finish_stream(self) -> None:
        self.finished = True

    async def remove(self) -> None:
        self.window.drop_live(self)


class QtThoughtBlock(QtLiveBlock):
    event_kind = ThinkingTranscript


class QtUserInputBlock(QtLiveBlock):
    """The user's input row, shown when the turn starts; saved history replaces it."""

    event_kind = UserTranscript

    def __init__(self, window: QtHistoryWindow, text: str) -> None:
        super().__init__(window, text)
        self.finished = True
