"""Compact projection of the model's active channel members above the composer."""
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage

from toad.navigation_target import ThreadTarget

from agent_comms.ui_model.sidebar import ThreadRowModel
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

    @staticmethod
    def prepare_participants(people: tuple[ThreadRowModel, ...]) -> tuple[Content, Content]:
        """Prepare paint from the publication's already acquired row answers."""
        names = []
        summaries = []
        for presentation in people:
            summaries.append(f"{presentation.name}: {presentation.summary}")
            names.append(Content.styled(
                presentation.label, "$warning" if presentation.busy else "$text-muted",
            ).stylize(Style.from_meta({"@click": ("open_thread", (presentation.name,))})))
        content = Content.assemble("Active: ", Content(" · ").join(names)) if names else Content("No active turns")
        return content, Content("\n".join(summaries))

    def update_participants(self, content: Content, tooltip: Content) -> None:
        """Publish prepared native resources; unchanged paint needs no refresh."""
        previous = self.names.content
        if not isinstance(previous, Content) or not content.is_same(previous):
            self.names.update(content)
        if tooltip != self.tooltip:
            self.tooltip = tooltip
