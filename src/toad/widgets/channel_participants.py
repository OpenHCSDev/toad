"""Compact projection of the model's active channel members above the composer."""
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage

from toad.navigation_target import ThreadTarget

from agent_comms.presentation import ThreadView
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content
from textual.style import Style
from textual.widgets import Static

from toad.core.input_events import SelectTarget


class ParticipantNames(CoreEventReceiver, Static):
    def action_open_thread(self, name: str) -> None:
        self.publish_core(SelectTarget(ThreadTarget(name)))


class ChannelParticipants(VerticalScroll):
    DEFAULT_CSS = """
    ChannelParticipants {
        height: auto; max-height: 4; overflow-y: auto;
        padding: 0 1; color: $text-muted;
    }
    """

    def __init__(self):
        super().__init__()
        self.names = ParticipantNames(markup=False)

    def compose(self) -> ComposeResult:
        yield self.names

    def update_participants(self, people: tuple[ThreadView, ...]) -> None:
        names = []
        summaries = []
        for person in people:
            presentation = person.presentation
            summaries.append(f"{person.thread.name}: {presentation.summary}")
            names.append(Content.styled(
                presentation.label, "$warning" if presentation.busy else "$text-muted",
            ).stylize(Style.from_meta({"@click": ("open_thread", (person.thread.name,))})))
        content = Content.assemble("Active: ", Content(" · ").join(names)) if names else Content("No active turns")
        previous = self.names.content
        if not isinstance(previous, Content) or not content.is_same(previous):
            self.names.update(content)
        tooltip = Content("\n".join(summaries))
        if tooltip != self.tooltip:
            self.tooltip = tooltip
