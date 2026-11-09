"""The current external CLI item, drawn beside finished history."""

from functools import partial

from agent_comms.transcript.external_transcript import DraftRow
from agent_comms.transcript.transcript_drafts import NoDraft
from metaclass_registry.mro_dispatch import handles
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.widget import Widget

from toad.block_navigation import ConversationBlock
from toad.core.projection import MroProjection
from toad.native_style import AutoHeight
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.linked_rows import LinkedRows, ReferenceRendering
from toad.widgets.transcript_fragments import DraftBlocksRenderTask, FragmentPlan
from toad.widgets.transcript_lines import (
    AcquiredRows,
    BlockLines,
    LinePreparation,
    NoRows,
    NoStyledLines,
    RowAcquisition,
    TranscriptLinesBatchRenderTask,
)
from toad.worker_group import WorkerGroup


class CliDraftRender(WorkerGroup):
    """Draws the current draft; clearing the draft cancels it."""



class DraftRender(MroProjection[None]):
    """A shown draft is drawn; with no draft there is nothing to draw."""

    @handles(DraftRow)
    def shown(self, draft: DraftRow, widget: CliDraft) -> None:
        CliDraftRender.run_on(widget, widget._draw)

    @handles(NoDraft)
    def absent(self, draft: NoDraft, widget: CliDraft) -> None:
        """Nothing to draw."""


DRAFT_RENDER = DraftRender()


class CliDraft(AutoHeight, ReferenceRendering, ConversationBlock, LinkedRows, Widget):
    """Core's current CLI answer, drawn with the committed transcript renderer."""


    def __init__(self):
        super().__init__()
        self.draft: DraftRow | NoDraft = NoDraft()
        self._lines: BlockLines = NoStyledLines()
        self._plan = FragmentPlan()
        self._rows: RowAcquisition = NoRows()
        self._width = 0
        self.display = False

    def invalidate_lines(self) -> None:
        self._lines = NoStyledLines(self._width)
        self._request_render()
        self.refresh(layout=True)

    def clear(self) -> None:
        # A render in flight drew the previous draft; it stops before it can show it.
        CliDraftRender.cancel_all(self)
        self.draft = NoDraft()
        self._plan = FragmentPlan()
        self._rows = NoRows()
        self._lines = NoStyledLines(self._width)
        self.display = False

    def show(self, draft: DraftRow, *, resolve_sent) -> None:
        if draft == self.draft:
            return
        self._plan = FragmentPlan.read(draft.events, resolve_sent=resolve_sent)
        self.draft = draft
        self._request_render()

    def _request_render(self) -> None:
        if self.is_attached and not CliDraftRender.running_on(self):
            DRAFT_RENDER.project_value(self.draft, self)

    async def _draw(self) -> None:
        while self.is_attached:
            draft = self.draft
            width = self._width or self.query_ancestor(HistoryWindow).content_size.width
            if width <= 0:
                return
            theme = self.app.colours.line_theme
            blocks = await self.app.render_processes.submit(DraftBlocksRenderTask(self._plan))
            source = LinePreparation(blocks, theme)
            # A growing draft changes at its end: what it already drew keeps its rows.
            ((request, prepared),) = await TranscriptLinesBatchRenderTask.render_for(
                self, (source,), previous=(self._rows,))
            if not request.context.current_for(self):
                continue
            if not self.is_attached:
                return
            if ((draft.turn_id, draft.item_id) != (self.draft.turn_id, self.draft.item_id)
                    or theme is not self.app.colours.line_theme):
                continue
            window = self.query_ancestor(HistoryWindow)
            window.keep_reader()
            rows = self._lines.height
            self._lines = prepared.wrap(self._width or width, self.app.colours.line_renderer)
            self._rows = AcquiredRows(source, self._lines, request.context)
            self.display = True
            # A chunk that ends on the row the draft already had changes paint, not geometry:
            # asking for layout on every chunk re-arranged the window once per streamed token.
            self.refresh(layout=self._lines.height != rows)
            if window.follows_tail:
                self.call_after_refresh(window.anchor)
            if draft == self.draft:
                return

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        if width != self._width:
            self._width = width
            self._lines = self._lines.rewrap(width)
            self._lines.request_styling(partial(self.call_later, self._request_render))
        return self._lines.height

    def render_line(self, y: int, paint: PaintState) -> Strip:
        lines = self._lines
        if y >= lines.height:
            return self.blank_row(self._width, paint)
        return self.on_background(lines.strips_at(self.link_place)[y], paint, y)

    @property
    def line_sets(self) -> tuple[BlockLines, ...]:
        return (self._lines,)

