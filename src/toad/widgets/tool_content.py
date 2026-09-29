"""Prepared tool output widgets; content decisions belong to tool_output."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual import containers
from textual.content import Content
from textual.widgets import Static

from toad.widgets.prepared_markdown import PreparedConversationMarkdown

if TYPE_CHECKING:
    from textual.signal import Signal
    from textual.screen import Screen
    from textual.worker import Worker
    from toad.widgets.patch_diff import PreparedPatch


class TextContent(Static):
    DEFAULT_CSS = """
    TextContent 
    {
        height: auto;
    }
    """


class MarkdownContent(PreparedConversationMarkdown):
    pass


@dataclass(frozen=True)
class PatchWarmup:
    source: str
    theme: tuple[bool, bool]
    result: "asyncio.Future[PreparedPatch | None]"


class ToolCallDiff(containers.VerticalGroup):
    DEFAULT_CSS = """
    ToolCallDiff {
        height: auto;
    }
    """

    def __init__(self, patch: str, *, warmup: PatchWarmup | None = None) -> None:
        self.patch = patch
        self._warmup = warmup
        prepared = (warmup.result.result() if warmup is not None and warmup.source == patch
                    and warmup.result.done() and not warmup.result.cancelled() else None)
        self._prepared_patch: PreparedPatch | None = prepared
        self._requested_theme: tuple[bool, bool] | None = None if prepared is None else prepared.theme
        self._preparation_generation = 0
        self._preparation_worker: Worker[None] | None = None
        self._visibility_signal: Signal[Screen] | None = None
        self._presentable = prepared is not None
        self.prepared = asyncio.Event()
        """Prepared data accepted for composition, not a terminal-paint receipt."""
        if prepared is not None:
            self.prepared.set()
        super().__init__()

    def compose(self) -> ComposeResult:
        from toad.widgets.patch_diff import PatchDiffView

        prepared = self._prepared_patch
        if not self._presentable or prepared is None or prepared.theme != self._theme_key():
            from toad.widgets.throbber import Throbber

            yield Static("Preparing diff…")
            indicator = Throbber()
            indicator.busy = True
            indicator.styles.height = 1
            yield indicator
        elif prepared.patch is None:
            assert prepared.plain_text is not None
            highlighted = Content.from_rich_text(prepared.plain_text)
            yield TextContent(Content(self.patch, list(highlighted.spans)))
        else:
            mode = self.app.settings.diff.view
            yield PatchDiffView(prepared.patch, prepared=prepared,
                                 split=mode.split, auto_split=mode.auto_split,
                                 wrap=self.app.settings.diff.wrap.enabled,
                                 annotations=self.app.settings.diff.annotations)

    def _theme_key(self) -> tuple[bool, bool]:
        theme = self.app.current_theme
        return theme.ansi, theme.dark

    def on_mount(self) -> None:
        self._ensure_preparation()
        self.publish_if_ready()

    def on_show(self) -> None:
        self._ensure_preparation()
        self.publish_if_ready()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_mounted:
            self._ensure_preparation()

    def _ensure_preparation(self) -> None:
        if not self.is_attached or self._pruning:
            return
        theme = self._theme_key()
        if self._requested_theme == theme:
            return
        self._requested_theme = theme
        self._preparation_generation += 1
        self.prepared.clear()
        self._preparation_worker = self.run_worker(
            self._prepare(self._preparation_generation, self.patch, theme),
            group="patch-preparation", exclusive=True,
        )

    async def _prepare(self, generation: int, source: str, theme: tuple[bool, bool]) -> None:
        from toad.render_tasks import PatchRenderTask

        try:
            warmup = self._warmup
            prepared = None
            if warmup is not None and warmup.source == source and warmup.theme == theme:
                await asyncio.wait((warmup.result,))
                prepared = warmup.result.result()
            if prepared is None:
                prepared = await self.app.render_processes.submit(PatchRenderTask(source, *theme))
            if (generation != self._preparation_generation or self.patch != source
                    or not self.is_attached or self._pruning):
                return
            if self._theme_key() != theme:
                self._requested_theme = None
                self._ensure_preparation()
                return
            self._prepared_patch = prepared
            self._presentable = False
            self.publish_if_ready()
        finally:
            if generation == self._preparation_generation:
                self._preparation_worker = None

    def publish_if_ready(self, _screen: "Screen | None" = None) -> None:
        if (self._presentable or self._prepared_patch is None or not self.is_attached
                or self._pruning or self._prepared_patch.theme != self._theme_key()):
            return
        from toad.widgets.tool_call import ToolCall

        tool = self.query_ancestor(ToolCall)
        if not tool.expanded or (tool._auto_expanded and not tool._visible_in_window()):
            if self._visibility_signal is None:
                self._visibility_signal = self.screen.screen_layout_refresh_signal
                self._visibility_signal.subscribe(self, self.publish_if_ready, immediate=True)
            return
        if self._visibility_signal is not None:
            self._visibility_signal.unsubscribe(self)
            self._visibility_signal = None
        self._presentable = True
        self.prepared.set()
        self.refresh(recompose=True)

    def on_unmount(self) -> None:
        self._preparation_generation += 1
        self._requested_theme = None
        self._prepared_patch = None
        self._warmup = None
        self._presentable = False
        self.prepared.clear()
        if self._preparation_worker is not None:
            self._preparation_worker.cancel()
            self._preparation_worker = None
        if self._visibility_signal is not None:
            self._visibility_signal.unsubscribe(self)
            self._visibility_signal = None


