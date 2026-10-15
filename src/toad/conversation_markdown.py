from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.layout import WidgetPlacement
from textual.widgets import Markdown

from toad.layout import trim_trailing_margin
from toad.block_content import MarkdownBlockContent, MarkdownFence
from toad.markdown_links import LinkContext, MessageMarkdownParser
from toad.widgets.transcript_lines import OpensLinks


class ConversationCodeFence(MarkdownFence):
    @classmethod
    def clipboard_source(cls, markdown: str | None, code: str | None) -> str | None:
        return code

    @classmethod
    def prompt_source(cls, markdown: str | None, code: str | None) -> str | None:
        return markdown


class ConversationMarkdown(OpensLinks, Markdown):
    """Textual blocks borrow the same syntax, links and opening actions as rows."""

    BLOCKS = {
        **MarkdownBlockContent.blocks_for(Markdown.BLOCKS),
        "fence": ConversationCodeFence,
    }

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("parser_factory", self._make_parser)
        kwargs.setdefault("open_links", False)
        super().__init__(*args, **kwargs)

    def _make_parser(self) -> MessageMarkdownParser:
        return MessageMarkdownParser(LinkContext.containing(self))

    async def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        self.action_link(event.href)

    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)
