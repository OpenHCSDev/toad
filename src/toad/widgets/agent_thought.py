from __future__ import annotations
from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ThinkingCategory

from agent_comms.transcript_events import ThinkingTranscript
from typing import ClassVar

from textual.binding import Binding, BindingType
from toad.widgets.streaming_markdown import StreamingMarkdown
from toad.widgets.message_filter import CategorizedBlock, MessageCategory



class AgentThought(ConversationBlock, CategorizedBlock, StreamingMarkdown, can_focus=True):
    """The agent's 'thoughts'."""

    DEFAULT_CSS = """
    AgentThought {
        background: $primary-muted 20%;
        color: $text-primary;
        min-height: 1;
        margin: 0 1 1 0;
        padding:  0 1 0 1;
        border: none;
        border-left: tall $primary;
        overflow-x: auto;
        scrollbar-size-horizontal: 0;
        layout: stream;

        &.-loading {
            background: transparent !important;
            padding: 0;
            margin: 0;
        }
        overflow-y: hidden;

        MarkdownParagraph {
            margin: 0;
        }

        &.-maximized {
            max-height: 100h;
            margin: 1 2;
            scrollbar-visibility: visible;
            &>* {
                padding-right: 1;
            }
        }
        &:focus {
            border-left: tall $primary;
        }
        &:ansi {
            background: ansi_default;
            border-left: tall ansi_blue;
        }
    }
    """

    TRANSCRIPT_EVENT = ThinkingTranscript

    @property
    def message_category(self) -> type[MessageCategory]:
        return ThinkingCategory

    HELP = """
## Agent thoughts

- **cursor keys** Scroll text
"""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("left", "scroll_left", "Scroll Left", show=False),
        Binding("right", "scroll_right", "Scroll Right", show=False),
        Binding("home", "scroll_home", "Scroll Home", show=False),
        Binding("end", "scroll_end", "Scroll End", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+pageup", "page_left", "Page Left", show=False),
        Binding("ctrl+pagedown", "page_right", "Page Right", show=False),
    ]

    ALLOW_MAXIMIZE = True

    def watch_loading(self, loading: bool) -> None:
        self.set_class(loading, "-loading")

    def on_mount(self) -> None:
        self.scroll_end()

    async def append_fragment(self, fragment: str) -> None:
        await super().append_fragment(fragment)
        self.scroll_end()
