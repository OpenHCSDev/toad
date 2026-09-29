from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import UserCategory
from textual.app import ComposeResult
from textual import containers
from toad.widgets.prepared_markdown import PreparedConversationMarkdown

from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.message_divider import MessageDivider, MessageClock, LiveMessageClock
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation



class UserInput(ConversationBlock, SnapshotPresentation, CategorizedBlock, containers.VerticalGroup):
    @property
    def message_category(self) -> type[MessageCategory]:
        return UserCategory

    def __init__(self, content: str, *, show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__()
        self.content = content
        self.show_divider = show_divider
        self.clock = clock

    def compose(self) -> ComposeResult:
        if self.show_divider:
            yield MessageDivider("User", clock=self.clock)
        with containers.HorizontalGroup(classes="user-input-body"):
            yield NonSelectableLabel("❯" if self.show_divider else " ", id="prompt")
            yield PreparedConversationMarkdown(self.content, id="content")

    def get_clipboard_text(self) -> str | None:
        return self.content
