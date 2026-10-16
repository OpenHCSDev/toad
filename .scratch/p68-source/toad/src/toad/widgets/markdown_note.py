from toad.block_navigation import ConversationBlock
from toad.widgets.line_markdown import LineMarkdown


class MarkdownNote(ConversationBlock, LineMarkdown):
    """A note in the conversation, drawn as prepared lines like any response."""
