from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import UserCategory
from textual.app import ComposeResult
from textual import containers
from toad.widgets.line_markdown import LineMarkdown

from toad.line_blocks import Divider, UserRole
from toad.widgets.message_divider import MessageDivider, MessageClock, LiveMessageClock
from toad.widgets.message_filter import MessageCategory
from toad.widgets.committed_presentation import CAPTURED_CLAIM, CommitClaim, SnapshotPresentation



class UserInput(ConversationBlock, SnapshotPresentation, containers.VerticalGroup):
    DEFAULT_CSS = """
    UserInput {
        background: transparent;
        padding: 0;
        margin: 0 0 1 0;
    }
    """

    @property
    def message_category(self) -> type[MessageCategory]:
        return UserCategory

    def __init__(self, content: str, *, claim: CommitClaim = CAPTURED_CLAIM,
                 show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__()
        self.content = content
        self.show_divider = show_divider
        self.clock = clock
        self.claim = claim

    @property
    def commit_claim(self):
        return self.claim

    def compose(self) -> ComposeResult:
        if self.show_divider:
            yield MessageDivider(Divider.titled("User", UserRole), clock=self.clock)
        # The same Body block committed history draws for this message.
        yield LineMarkdown(self.content, bar=UserRole, markdown=False, id="content")

    def get_clipboard_text(self) -> str | None:
        return self.content
