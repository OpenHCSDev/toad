"""The current external CLI item, drawn beside finished history."""

from agent_comms.external_transcript import ExternalDraftRow
from toad.markdown_links import LinkContext, ReferenceRendering
from textual.widget import Widget
from textual.worker import Worker
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from toad.block_navigation import ConversationBlock
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.transcript_lines import BlockLines, LinkedRows, LinePreparation, TranscriptLinesRenderTask
from toad.widgets.transcript_fragments import FragmentLineConsumer


class CliDraft(ReferenceRendering, ConversationBlock, LinkedRows, Widget):
    """Core's current CLI answer, drawn with the committed transcript renderer."""

    DEFAULT_CSS = "CliDraft { height: auto; }"

    def __init__(self):
        super().__init__()
        self.draft: ExternalDraftRow | None = None
        self._lines: BlockLines | None = None
        self._width = 0
        self._render_worker: Worker[None] | None = None
        self.display = False

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)

    def invalidate_lines(self, change=None) -> None:
        self._lines = None
        self._request_render()
        self.refresh(layout=True)

    def show(self, draft: ExternalDraftRow | None) -> None:
        if draft == self.draft:
            return
        self.draft = draft
        if draft is None:
            self.display = False
            self._lines = None
        else:
            self._request_render()

    def _request_render(self) -> None:
        if self.is_attached and (self._render_worker is None or self._render_worker.is_finished):
            self._render_worker = self.run_worker(self._draw(), group="cli-draft")

    async def _draw(self) -> None:
        while self.is_attached and self.draft is not None:
            draft = self.draft
            width = self._width or self.query_ancestor(HistoryWindow).content_size.width
            if width <= 0:
                return
            theme = self.app.colours.line_theme
            consumer = FragmentLineConsumer(show_divider=True)
            for event in draft.events:
                consumer.dispatch_sync(event)
            context = await LinkContext.acquire(self)
            source = await self.app.render_processes.submit(
                TranscriptLinesRenderTask(LinePreparation(tuple(consumer.blocks), theme), context))
            if not context.current_for(self):
                continue
            if not self.is_attached or self.draft is None:
                return
            if ((draft.turn_id, draft.item_id) != (self.draft.turn_id, self.draft.item_id)
                    or theme is not self.app.colours.line_theme):
                continue
            window = self.query_ancestor(HistoryWindow)
            window.keep_reader()
            self._lines = source.wrap(self._width or width, self.app.colours.line_renderer)
            self.display = True
            self.refresh(layout=True)
            if window.follows_tail:
                self.call_after_refresh(window.anchor)
            if draft == self.draft:
                return

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        if width != self._width:
            self._width = width
            if self._lines is not None:
                self._lines = self._lines.rewrap(width)
            else:
                self.call_later(self._request_render)
        return self._lines.height if self._lines is not None else 0

    def render_line(self, y):
        lines = self._lines
        if lines is None or y >= lines.height:
            return self.blank_row(self._width)
        return self.on_background(lines.strips_at(id(self))[y])

    def get_selection(self, selection):
        text = "\n".join(self.render_line(y).text.rstrip()
                         for y in range(self._lines.height if self._lines is not None else 0))
        return selection.extract(text), "\n"

