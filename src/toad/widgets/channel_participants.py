"""Compact projection of the model's active channel members above the composer."""

from agent_comms import ThreadView
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content
from textual.style import Style
from textual.widgets import Static

from toad.widgets.comms_sidebar import SelectTarget


class ParticipantNames(Static):
    def action_open_thread(self, name: str) -> None:
        self.post_message(SelectTarget(name, "thread"))


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
        self._content_signature: Content | None = None

    def compose(self) -> ComposeResult:
        yield self.names

    def update_participants(self, people: tuple[ThreadView, ...]) -> None:
        names = []
        for person in people:
            presentation = person.presentation
            names.append(Content.styled(
                presentation.label, "$warning" if presentation.busy else "$text-muted",
            ).stylize(Style.from_meta({"@click": ("open_thread", (person.thread.name,))})))
        content = Content.assemble("Active: ", Content(" · ").join(names)) if names else Content("No active turns")
        if content != self._content_signature:
            self._content_signature = content
            self.names.update(content)
            self.tooltip = Content("\n".join(
                f"{person.thread.name}: {person.presentation.summary}" for person in people
            ))
