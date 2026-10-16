"""The active members of a channel, shown above the composer."""
from agent_comms.ui_model.sidebar import ThreadRowModel
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content
from textual.style import Style
from textual.widgets import Static

from toad.line_blocks import OpenTarget
from toad.widgets.transcript_lines import OpensLinks


class ParticipantNames(OpensLinks, Static):
    """The names of a channel's active threads; each opens its thread."""


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
        """What to draw for these members, built off the UI thread."""
        names = []
        summaries = []
        for presentation in people:
            summaries.append(f"{presentation.name}: {presentation.summary}")
            names.append(Content.styled(
                presentation.label, "$warning" if presentation.status.busy else "$text-muted",
            ).stylize(Style.from_meta({"@click": OpenTarget(presentation.name).click})))
        content = Content.assemble("Active: ", Content(" · ").join(names)) if names else Content("No active turns")
        return content, Content("\n".join(summaries))

    def update_participants(self, content: Content, tooltip: Content) -> None:
        """Draw prepared names; unchanged names are not redrawn."""
        previous = self.names.content
        if not isinstance(previous, Content) or not content.is_same(previous):
            self.names.update(content)
        if tooltip != self.tooltip:
            self.tooltip = tooltip
