"""The current external CLI item, drawn beside finished history."""

from agent_comms.external_transcript import ExternalDraftRow
from agent_comms.mro_dispatch import handles
from toad.markdown_links import LinkContext, ReferenceRendering
from textual.widget import Widget
from textual.worker import Worker
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from toad.block_navigation import ConversationBlock
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.transcript_lines import LinkedRows, LinePreparation, TranscriptLinesRenderTask, PreparedLines
from toad.widgets.transcript_fragments import prepare_transcript_fragments, Shown
from toad.line_blocks import ToggleDetails


class CliDraft(ReferenceRendering, ConversationBlock, LinkedRows, Widget):
    """Core's current CLI answer, drawn with the committed transcript renderer."""

    DEFAULT_CSS = "CliDraft { height: auto; }"

    def __init__(self):
        super().__init__()
        self.draft: ExternalDraftRow | None = None
        self.shown = Shown()
        self._lines: PreparedLines | None = None
        self._width = 0
        self._render_worker: Worker[None] | None = None
        self.display = False

    @property
    def line_width(self) -> int:
        return self._width or self.query_ancestor(HistoryWindow).content_size.width

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)

    def invalidate_lines(self, change=None) -> None:
        self._lines = None
        self._request_render()
        self.refresh(layout=True)

    def show(self, draft: ExternalDraftRow | None) -> None:
        if draft == self.draft:
            return
        if (self.draft is None or draft is None
                or (self.draft.turn_id, self.draft.item_id) != (draft.turn_id, draft.item_id)):
            self.shown = Shown()
        self.draft = draft
        if draft is None:
            self.display = False
            self._lines = None
        else:
            self._request_render()

    @handles(ToggleDetails)
    def toggle_details(self, link: ToggleDetails) -> None:
        self.shown = self.shown.toggled()
        self.invalidate_lines()

    def _request_render(self) -> None:
        if self.is_attached and (self._render_worker is None or self._render_worker.is_finished):
            self._render_worker = self.run_worker(self._draw(), group="cli-draft")

    async def _draw(self) -> None:
        while self.is_attached and self.draft is not None:
            draft = self.draft
            shown = self.shown
            width = self.line_width
            if width <= 0:
                return
            theme = self.app.colours.line_theme
            fragments = await prepare_transcript_fragments(draft.events, self.app.render_processes)
            blocks = tuple(block for fragment in fragments for block in fragment.blocks(shown))
            context = await LinkContext.acquire(self)
            request = TranscriptLinesRenderTask(LinePreparation(blocks, width, theme), context)
            lines = await self.app.render_processes.submit(request)
            if not self.is_attached or self.draft is None:
                return
            if draft != self.draft or shown != self.shown or not request.current_for(self):
                continue
            window = self.query_ancestor(HistoryWindow)
            window.keep_reader()
            self._lines = lines
            self.display = True
            self.refresh(layout=True)
            if window.follows_tail:
                self.call_after_refresh(window.anchor)
            return

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        if width != self._width:
            self._width = width
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

