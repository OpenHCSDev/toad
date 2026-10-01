from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import UserCategory
from textual.app import ComposeResult
from textual import containers
from toad.widgets.prepared_markdown import PreparedConversationMarkdown

from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.message_divider import MessageDivider, MessageClock, LiveMessageClock
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import CAPTURED_CLAIM, CommitClaim, SnapshotPresentation



class UserInput(ConversationBlock, SnapshotPresentation, CategorizedBlock, containers.VerticalGroup):
    DEFAULT_CSS = """
    UserInput {
        background: transparent;
        padding: 0;
        margin: 0 1 1 0;
        & > .user-input-body {
            border-left: blank $secondary;
            background: $secondary 15%;
            padding: 0 1 0 0;
        }
        Markdown {
            padding:0 2 0 0;
        }
        MarkdownFence {
            margin: 0 2 1 0;
        }
        #prompt {
            margin: 0 1 0 0;
            color: $text-secondary;
        }
        &:ansi > .user-input-body {
            background: ansi_default;
            border-left: tall ansi_cyan;
        }
    }
    """

    @property
    def message_category(self) -> type[MessageCategory]:
        return UserCategory

    def __init__(self, content: str, *, claim: CommitClaim = CAPTURED_CLAIM, show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
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
            yield MessageDivider("User", clock=self.clock)
        with containers.HorizontalGroup(classes="user-input-body"):
            yield NonSelectableLabel("❯" if self.show_divider else " ", id="prompt")
            yield PreparedConversationMarkdown(self.content, id="content")

    def get_clipboard_text(self) -> str | None:
        return self.content
