"""Prepared tool output widgets; content decisions belong to tool_output."""

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from textual import containers
from textual.content import Content
from textual.widgets import Static
from agent_comms.declared_family import DeclaredFamily
from agent_comms.lifecycle import LifecycleState

from toad.render_tasks import PatchRenderTask
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

    def prepared_for(self, source: str) -> "PreparedPatch | None":
        if source != self.source:
            return None
        if self.result.cancelled() or not self.result.done():
            return None
        return self.result.result()


@dataclass(frozen=True)
class PatchPreparationTicket:
    generation: int
    task: PatchRenderTask


class PatchPublication(DeclaredFamily, LifecycleState, affix="PatchPublication"):
    @classmethod
    def successors(cls) -> tuple[type[PatchPublication], ...]:
        return (WaitingPatchPublication, PreparedPatchPublication)

    def publish(self, view: "ToolCallDiff") -> PatchPublication:
        return self

    @abstractmethod
    def compose(self, view: "ToolCallDiff") -> ComposeResult: ...


class WaitingPatchPublication(PatchPublication):
    def compose(self, view: "ToolCallDiff") -> ComposeResult:
        from toad.widgets.throbber import Throbber

        yield Static("Preparing diff…")
        indicator = Throbber()
        indicator.busy = True
        indicator.styles.height = 1
        yield indicator


@dataclass(frozen=True)
class PreparedPatchPublication(PatchPublication):
    value: "PreparedPatch"
    task: PatchRenderTask

    def compose(self, view: "ToolCallDiff") -> ComposeResult:
        yield from WaitingPatchPublication().compose(view)

    @classmethod
    def successors(cls) -> tuple[type[PatchPublication], ...]:
        return (WaitingPatchPublication, PublishedPatchPublication)

    def publish(self, view: "ToolCallDiff") -> PatchPublication:
        if self.task != view.render_task:
            return self
        from toad.widgets.tool_call import ToolCall

        tool = view.query_ancestor(ToolCall)
        if not tool.content_presentable:
            view.wait_for_visibility()
            return self
        view.stop_visibility_watch()
        view.prepared.set()
        return PublishedPatchPublication(self.value, self.task)


class PublishedPatchPublication(PreparedPatchPublication):
    @classmethod
    def successors(cls) -> tuple[type[PatchPublication], ...]:
        return (WaitingPatchPublication, PreparedPatchPublication)

    def publish(self, view: "ToolCallDiff") -> PatchPublication:
        return self

    def compose(self, view: "ToolCallDiff") -> ComposeResult:
        if self.task != view.render_task:
            yield from WaitingPatchPublication().compose(view)
        elif self.value.patch is None:
            assert self.value.plain_text is not None
            highlighted = Content.from_rich_text(self.value.plain_text)
            yield TextContent(Content(view.patch, list(highlighted.spans)))
        else:
            from toad.widgets.patch_diff import PatchDiffView

            mode = view.app.settings.diff.view
            yield PatchDiffView(self.value.patch, prepared=self.value,
                                split=mode.split, auto_split=mode.auto_split,
                                wrap=view.app.settings.diff.wrap.enabled,
                                annotations=view.app.settings.diff.annotations)


class ToolCallDiff(containers.VerticalGroup):
    DEFAULT_CSS = """
    ToolCallDiff {
        height: auto;
    }
    """

    def __init__(self, patch: str, *, warmup: PatchWarmup | None = None) -> None:
        self.patch = patch
        self._warmup = warmup
        prepared = None if warmup is None else warmup.prepared_for(patch)
        task = None if prepared is None else PatchRenderTask(patch, *prepared.theme)
        self.publication: PatchPublication = (WaitingPatchPublication() if prepared is None
                                             else PublishedPatchPublication(prepared, task))
        self._requested_task: PatchRenderTask | None = task
        self._preparation_generation = 0
        self._preparation_worker: Worker[None] | None = None
        self._visibility_signal: Signal[Screen] | None = None
        self.prepared = asyncio.Event()
        """Prepared data accepted for composition, not a terminal-paint receipt."""
        if prepared is not None:
            self.prepared.set()
        super().__init__()

    def compose(self) -> ComposeResult:
        yield from self.publication.compose(self)

    def _theme_key(self) -> tuple[bool, bool]:
        theme = self.app.current_theme
        return theme.ansi, theme.dark

    @property
    def render_task(self) -> PatchRenderTask:
        return PatchRenderTask(self.patch, *self._theme_key())

    @property
    def render_active(self) -> bool:
        return self.is_attached and not self._pruning

    @property
    def preparation_ticket(self) -> PatchPreparationTicket:
        return PatchPreparationTicket(self._preparation_generation, self.render_task)

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
        if not self.render_active:
            return
        task = self.render_task
        if self._requested_task == task:
            return
        self._requested_task = task
        self._preparation_generation += 1
        self.prepared.clear()
        self._preparation_worker = self.run_worker(
            partial(self._prepare, self.preparation_ticket),
            group="patch-preparation", exclusive=True,
        )

    async def _prepare(self, ticket: PatchPreparationTicket) -> None:
        try:
            warmup = self._warmup
            prepared = None
            if warmup is not None and PatchRenderTask(warmup.source, *warmup.theme) == ticket.task:
                await asyncio.wait((warmup.result,))
                prepared = warmup.result.result()
            if prepared is None:
                prepared = await self.app.render_processes.submit(ticket.task)
            if not self.render_active:
                return
            if ticket != self.preparation_ticket:
                self._ensure_preparation()
                return
            self.publication = PreparedPatchPublication(prepared, ticket.task)
            self.publish_if_ready()
        finally:
            if ticket.generation == self._preparation_generation:
                self._preparation_worker = None

    def publish_if_ready(self, _screen: "Screen | None" = None) -> None:
        if not self.render_active:
            return
        publication = self.publication.publish(self)
        if publication is not self.publication:
            self.publication = publication
            self.refresh(recompose=True)

    def wait_for_visibility(self) -> None:
        if self._visibility_signal is None:
            self._visibility_signal = self.screen.screen_layout_refresh_signal
            self._visibility_signal.subscribe(self, self.publish_if_ready, immediate=True)

    def stop_visibility_watch(self) -> None:
        if self._visibility_signal is not None:
            self._visibility_signal.unsubscribe(self)
            self._visibility_signal = None

    def on_unmount(self) -> None:
        self._preparation_generation += 1
        self._requested_task = None
        self.publication = WaitingPatchPublication()
        self._warmup = None
        self.prepared.clear()
        if self._preparation_worker is not None:
            self._preparation_worker.cancel()
            self._preparation_worker = None
        self.stop_visibility_watch()
