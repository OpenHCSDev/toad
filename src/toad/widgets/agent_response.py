from textual.reactive import var
from textual.widget import Widget
from toad.widgets.streaming_markdown import StreamingMarkdown
from agent_comms import MessageRoute
from toad.widgets.route_header import RouteHeader


SYSTEM = """\
If asked to output code add inline documentation in the google style format, and always use type hinting where appropriate.
Avoid using external libraries where possible, and favor code that writes output to the terminal.
When asked for a table do not wrap it in a code fence.
"""


class AgentResponse(StreamingMarkdown):
    DEFAULT_CLASSES = "block"
    block_cursor_offset = var(-1)

    def __init__(self, markdown: str | None = None, *, route: MessageRoute | None = None,
                 paginate: bool = True) -> None:
        prefix = (RouteHeader(route),) if route is not None else ()
        super().__init__(markdown, paginate=paginate, prefix=prefix)
        self.route = route
        if route is not None:
            self.add_class("-routed")

    def block_cursor_clear(self) -> None:
        self.block_cursor_offset = -1

    def block_cursor_up(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            if self.children:
                self.block_cursor_offset = len(self.children) - 1
            else:
                return None
        else:
            self.block_cursor_offset -= 1

        if self.block_cursor_offset == -1:
            return None
        try:
            return self.children[self.block_cursor_offset]
        except IndexError:
            self.block_cursor_offset = -1
            return None

    def block_cursor_down(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            if self.children:
                self.block_cursor_offset = 0
            else:
                return None
        else:
            self.block_cursor_offset += 1
        if self.block_cursor_offset >= len(self.children):
            self.block_cursor_offset = -1
            return None
        try:
            return self.children[self.block_cursor_offset]
        except IndexError:
            self.block_cursor_offset = -1
            return None

    def get_cursor_block(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            return None
        return self.children[self.block_cursor_offset]

    def block_select(self, widget: Widget) -> None:
        self.block_cursor_offset = self.children.index(widget)
