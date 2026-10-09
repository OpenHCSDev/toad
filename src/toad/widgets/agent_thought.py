from __future__ import annotations
from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ThinkingCategory

from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.containers import VerticalGroup
from toad.line_blocks import ThinkingRole
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_filter import CategorizedBlock, MessageCategory



class AgentThought(ConversationBlock, CategorizedBlock, VerticalGroup, can_focus=True):
    """The agent's 'thoughts', drawn as prepared lines."""

    DEFAULT_CSS = """
    AgentThought {
        background: $primary-muted 20%;
        color: $text-primary;
        min-height: 1;
        margin: 0 1 1 0;
        padding:  0 1 0 1;
        border: none;
        border-left: tall $primary;
        height: auto;

        &.-loading {
            background: transparent !important;
            padding: 0;
            margin: 0;
        }
        overflow-y: hidden;

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

    def __init__(self, markdown: str | None = None) -> None:
        super().__init__()
        self.body = LineMarkdown(markdown or "", role=ThinkingRole)

    def compose(self):
        yield self.body

    async def append_fragment(self, fragment: str) -> None:
        self.loading = False
        self.body.append(fragment)

    async def finish_stream(self) -> None:
        """Appends draw as they arrive; there is no stream to flush."""
