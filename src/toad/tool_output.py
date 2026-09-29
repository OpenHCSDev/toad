"""Decoded tool output owns its presentation and preparation lifetime.

ACP dictionaries end at ``decode_content``. Presentation cases and the mounted
output owner operate on captured values, including when an adapter mutates an
earlier dictionary or changes Read's filename without changing its text.
"""

import asyncio
from abc import abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
import re
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.lifecycle import LifecycleState
from rich.text import Text
from textual.content import Content
from textual.css.query import NoMatches
from textual.widget import Widget

from acp import schema
from agent_comms.mro_dispatch import MroDispatch, handles
from toad.widgets.tool_content import (
    MarkdownContent, PatchWarmup, TextContent, ToolCallDiff,
)
from toad.widgets.worker_static import WorkerStatic

if TYPE_CHECKING:
    from textual.worker import Worker
    from toad.widgets.tool_call import ToolCall


class ToolOutputPart(DeclaredFamily, affix="ToolOutputPart"):
    """A captured output value; a case owns rendering and preparation hooks."""

    available = True

    @abstractmethod
    def compose(self, view: Widget) -> tuple[Widget, ...]: ...

    def permission_preview(self) -> ToolOutputPart | None:
        """Permission previews admit only text and file diffs."""
        return None

    @property
    def retained_text(self) -> Content | None:
        return None

    def update_widget(self, previous: ToolOutputPart, widget: Widget) -> bool:
        return False

    def begin_preparation(self, theme: tuple[bool, bool]) -> bool:
        return False

    async def prepare(self, view: ToolCall) -> None:
        pass

    def retire_preparation(self) -> None:
        pass

    @property
    def preview_dimensions(self) -> tuple[int, int] | None:
        return None


@dataclass(frozen=True)
class TextToolOutputPart(ToolOutputPart):
    text: str

    def permission_preview(self) -> ToolOutputPart:
        # Permission questions interpret all text as Markdown, independent of
        # the streaming output's Read/ANSI/literal heuristics.
        return MarkdownToolOutputPart(self.text)

    @classmethod
    @abstractmethod
    def accepts(cls, text: str, read_path: str | None) -> bool: ...

    @classmethod
    def from_text(cls, text: str, read_path: str | None) -> TextToolOutputPart:
        # Text presentation is not prescribed by ACP. The member owns its
        # heuristic, and new cases never add a second consumer inventory.
        candidates = [member for member in cls.members_with(SpecificTextToolOutputPart)
                      if member.accepts(text, read_path)] or [
                          member for member in cls.members_with(LiteralTextToolOutputPart)
                          if member.accepts(text, read_path)
                      ]
        if len(candidates) != 1:
            raise ValueError("Tool text requires exactly one presentation owner")
        return candidates[0].capture(text, read_path)

    @classmethod
    def capture(cls, text: str, read_path: str | None) -> TextToolOutputPart:
        return cls(text)


class SpecificTextToolOutputPart(TextToolOutputPart):
    """An attested Read/ANSI/Markdown interpretation takes precedence."""


class LiteralTextToolOutputPart(TextToolOutputPart):
    """The remaining text is literal; member order is never priority."""


class RetainedTextToolOutputPart(TextToolOutputPart):
    @property
    @abstractmethod
    def retained_text(self) -> Content: ...

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return (TextContent(self.retained_text),)

    def update_widget(self, previous: ToolOutputPart, widget: Widget) -> bool:
        if previous.retained_text is None or type(widget) is not TextContent:
            return False
        state = widget.screen._select_state
        if widget.text_selection is not None or (state is not None and (
            state.start.content_widget is widget
            or (state.end is not None and state.end.content_widget is widget)
        )):
            return False
        widget.update(self.retained_text)
        return True


class PlainTextToolOutputPart(RetainedTextToolOutputPart, LiteralTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None

    @property
    def retained_text(self) -> Content:
        return Content(self.text)


class AnsiTextToolOutputPart(RetainedTextToolOutputPart, SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" in text

    @property
    def retained_text(self) -> Content:
        return Content.from_rich_text(Text.from_ansi(self.text))


class MarkdownToolOutputPart(SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" not in text and (
            "```" in text or re.search(r"^#{1,6}\s.*$", text, re.MULTILINE) is not None
        )

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return (MarkdownContent(self.text),)


@dataclass(frozen=True)
class ReadToolOutputPart(SpecificTextToolOutputPart):
    path: str

    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is not None

    @classmethod
    def capture(cls, text: str, read_path: str | None) -> ReadToolOutputPart:
        assert read_path is not None
        return cls(text, read_path)

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return (WorkerStatic.code(self.text, filename=self.path, line_numbers=False,
                                  themed=True, filename_only=True),)


class PatchPreparation:
    """One patch's optional background result; the App owns CPU admission."""

    def __init__(self) -> None:
        self.warmup: PatchWarmup | None = None

    def begin(self, source: str, theme: tuple[bool, bool]) -> None:
        self.retire()
        self.warmup = PatchWarmup(source, theme, asyncio.get_running_loop().create_future())

    def prepared_for(self, source: str):
        entry = self.warmup
        if entry is None or entry.source != source:
            return None
        if entry.result.cancelled() or not entry.result.done():
            return None
        return entry.result.result()

    async def prepare(self, view: ToolCall) -> None:
        from toad.render_tasks import PatchRenderTask

        entry = self.warmup
        assert entry is not None
        try:
            prepared = await view.app.prepare_background(PatchRenderTask(entry.source, *entry.theme))
            if not entry.result.done():
                entry.result.set_result(prepared)
        finally:
            # Cancellation/failure is a cache miss. Foreground preparation
            # remains the actual renderer and reports its own failures.
            if not entry.result.done():
                entry.result.set_result(None)

    def retire(self) -> None:
        entry, self.warmup = self.warmup, None
        if entry is not None and not entry.result.done():
            entry.result.cancel()


@dataclass(frozen=True)
class PatchToolOutputPart(ToolOutputPart):
    source: str
    preparation: PatchPreparation = field(default_factory=PatchPreparation, compare=False)

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return (ToolCallDiff(self.source, preparation=self.preparation),)

    def begin_preparation(self, theme: tuple[bool, bool]) -> bool:
        self.preparation.begin(self.source, theme)
        return True

    async def prepare(self, view: ToolCall) -> None:
        await self.preparation.prepare(view)

    def retire_preparation(self) -> None:
        self.preparation.retire()

    @property
    def preview_dimensions(self) -> tuple[int, int]:
        return len(self.source), self.source.count("\n")


@dataclass(frozen=True)
class FileDiffToolOutputPart(ToolOutputPart):
    path: str
    old_text: str | None
    new_text: str

    def permission_preview(self) -> ToolOutputPart:
        return self

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        from toad.widgets.diff_view import make_diff

        diff = make_diff(self.path, self.path, self.old_text, self.new_text)
        mode = view.app.settings.diff.view
        diff.split, diff.auto_split = mode.split, mode.auto_split
        return (diff,)


@dataclass(frozen=True)
class UnrenderedToolOutputPart(ToolOutputPart):
    """ACP media without an implemented viewer retains its expand affordance."""

    source: object

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return ()


@dataclass(frozen=True)
class TerminalToolOutputPart(ToolOutputPart):
    """ACP terminal output is projected by its existing terminal owner."""

    terminal_id: str
    available = False

    def compose(self, view: Widget) -> tuple[Widget, ...]:
        return ()


class ToolContentDecoder(MroDispatch):
    def __init__(self, read_path=None):
        self.read_path = read_path
        self.part = None

    @handles(schema.ContentToolCallContent)
    def content(self, item):
        self.dispatch_sync(item.content)

    @handles(schema.TextContentBlock)
    def text(self, item):
        self.part = TextToolOutputPart.from_text(item.text, self.read_path)

    @handles(schema.EmbeddedResourceContentBlock)
    def resource(self, item):
        self.dispatch_sync(item.resource)

    @handles(schema.TextResourceContents)
    def text_resource(self, item):
        self.part = PatchToolOutputPart(item.text) if item.mime_type == 'text/x-diff' else UnrenderedToolOutputPart(item)

    @handles(schema.FileEditToolCallContent)
    def diff(self, item):
        self.part = FileDiffToolOutputPart(item.path, item.old_text, item.new_text)

    @handles(schema.TerminalToolCallContent)
    def terminal(self, item):
        self.part = TerminalToolOutputPart(item.terminal_id)


def decode_content(item: object, read_path: str | None = None) -> ToolOutputPart:
    decoder = ToolContentDecoder(read_path)
    decoder.dispatch_sync(item)
    return decoder.part or UnrenderedToolOutputPart(item)


class ToolHydration(DeclaredFamily, LifecycleState, affix="ToolHydration"):
    pending = False
    schedulable = False

    @classmethod
    def successors(cls) -> tuple[type[ToolHydration], ...]:
        return (IdleToolHydration, WaitingToolHydration)

    def after_attempt(self) -> ToolHydration:
        return self


class IdleToolHydration(ToolHydration):
    pass


class WaitingToolHydration(ToolHydration):
    pending = True
    schedulable = True

    @classmethod
    def successors(cls) -> tuple[type[ToolHydration], ...]:
        return (IdleToolHydration, ScheduledToolHydration)


class ScheduledToolHydration(ToolHydration):
    pending = True

    def after_attempt(self) -> ToolHydration:
        return WaitingToolHydration()


class ToolOutput:
    """Mounted output, lazy hydration and cancellation belong to one lifetime."""

    def __init__(self, view: ToolCall) -> None:
        self._view = ref(view)
        self.parts: tuple[ToolOutputPart, ...] = ()
        self.suppress_auto_expansion = False
        self._mounted: tuple[ToolOutputPart, ...] | None = None
        self._lock = asyncio.Lock()
        self.hydration: ToolHydration = IdleToolHydration()
        self._warming: tuple[ToolOutputPart, ...] = ()
        self._theme: tuple[bool, bool] | None = None
        self._generation = 0
        self._worker: Worker[None] | None = None

    @property
    def view(self) -> ToolCall:
        view = self._view()
        assert view is not None
        return view

    def replace(self, tool_call: schema.ToolCall) -> None:
        self.suppress_auto_expansion = tool_call.kind == "read"
        raw_input = tool_call.raw_input or {}
        path = (raw_input.get("path") or raw_input.get("file_path") or raw_input.get("filePath")) if isinstance(raw_input, dict) else None
        read_path = path if self.suppress_auto_expansion and isinstance(path, str) else None
        parts = tuple(decode_content(item, read_path) for item in tool_call.content or ())
        if parts != self.parts:
            self.cancel_preparation()
            self.parts = parts

    @property
    def has_content(self) -> bool:
        return any(part.available for part in self.parts)

    def preview_fits(self) -> bool:
        dimensions = [size for part in self.parts if (size := part.preview_dimensions) is not None]
        return bool(dimensions) and sum(size[0] for size in dimensions) <= 16000 and sum(size[1] for size in dimensions) <= 200

    async def sync(self) -> None:
        from toad.widgets.conversation import Window

        async with self._lock:
            view = self.view
            parts = self.parts
            body = view.query_one_optional("#tool-content", Widget)
            if body is None:
                return
            if view.expanded and not view.content_presentable and not body.children:
                self.prepare_hidden()
                if not self.hydration.pending:
                    self.hydration = WaitingToolHydration()
                    try:
                        view.query_ancestor(Window).pending_tool_content.add(view)
                    except NoMatches:
                        pass
                    view.call_after_refresh(self.hydrate)
                return
            self.hydration = IdleToolHydration()
            try:
                view.query_ancestor(Window).pending_tool_content.discard(view)
            except NoMatches:
                pass
            if not view.expanded:
                self.cancel_preparation()
                if body.children:
                    await body.remove_children()
                self._mounted = None
            elif self._mounted != parts:
                retained = len(parts) == len(self._mounted or ()) == len(body.children) == 1
                if not retained or not parts[0].update_widget(self._mounted[0], body.children[0]):
                    with view.app.batch_update():
                        await body.remove_children()
                        await body.mount_all(widget for part in parts for widget in part.compose(view))
                self._mounted = parts

    def prepare_hidden(self) -> None:
        view = self.view
        theme = (view.app.current_theme.ansi, view.app.current_theme.dark)
        if self.parts == self._warming and self._theme == theme:
            return
        self.cancel_preparation()
        self._warming, self._theme = self.parts, theme
        pending = tuple(part for part in self.parts if part.begin_preparation(theme))
        if pending:
            self._worker = view.run_worker(partial(self.prepare, self._generation, pending),
                                          group="hidden-patch-warmup", exclusive=True,
                                          exit_on_error=False)

    async def prepare(self, generation: int, parts: tuple[ToolOutputPart, ...]) -> None:
        view = self.view
        try:
            for part in parts:
                if generation != self._generation or not view.is_attached:
                    return
                try:
                    await part.prepare(view)
                except Exception as error:
                    view.log.warning("Background tool preparation failed", error)
        finally:
            if generation == self._generation:
                self._worker = None

    def cancel_preparation(self) -> None:
        self._generation += 1
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        for part in self._warming:
            part.retire_preparation()
        self._warming, self._theme = (), None

    def theme_changed(self) -> None:
        if self.hydration.pending and self.view.content_open:
            self.prepare_hidden()

    def hydrate_if_visible(self) -> None:
        if self.hydration.schedulable and self.view.content_in_view:
            self.hydration = ScheduledToolHydration()
            self.view.run_worker(self.hydrate, group="visible-content")

    async def hydrate(self) -> None:
        phase = self.hydration
        try:
            if phase.pending and self.view.content_in_view:
                await self.sync()
        finally:
            if self.hydration is phase:
                self.hydration = phase.after_attempt()

    def retire(self) -> None:
        from toad.widgets.conversation import Window

        self.cancel_preparation()
        self.hydration = IdleToolHydration()
        try:
            self.view.query_ancestor(Window).pending_tool_content.discard(self.view)
        except NoMatches:
            pass
        self._mounted = None
