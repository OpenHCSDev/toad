"""Viewport projections own which painted message widgets count as evidence."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_comms.messages import Message
from textual.geometry import Region
from textual.widget import Widget

from toad.widgets.irc_message import WireMessageRow


@dataclass(frozen=True)
class MessageViewport(ABC):
    history: Sequence[tuple[Message, WireMessageRow]]
    geometry: Mapping[Widget, tuple[Region, Region]]
    viewport: Region

    @abstractmethod
    def painted_widget(self, widget: WireMessageRow) -> Widget | None: ...

    def visible_rows(self) -> tuple[tuple[Message, Widget], ...]:
        rows = []
        for message, widget in self.history:
            painted = self.painted_widget(widget)
            placement = self.geometry.get(painted) if painted is not None else None
            if placement is None:
                continue
            region, clip = placement
            if (region.overlaps(self.viewport) and region.overlaps(clip)
                    and clip.overlaps(self.viewport)):
                rows.append((message, widget))
        return tuple(rows)


class AcknowledgementViewport(MessageViewport):
    def painted_widget(self, widget: WireMessageRow) -> Widget:
        return widget.read_ack_widget()


class NotificationViewport(MessageViewport):
    def painted_widget(self, widget: WireMessageRow) -> Widget | None:
        return widget.notification_widget()
