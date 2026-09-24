import asyncio
from copy import deepcopy
from dataclasses import dataclass
import re  # re2 doesn't have MULTILINE
from typing import TYPE_CHECKING, Iterable
from rich.text import Text
from rich.syntax import Syntax

from textual import on
from textual import events
from textual.app import ComposeResult
from textual import getters

from textual.content import Content
from textual.reactive import var
from textual.css.query import NoMatches
from textual import containers
from textual.widgets import Static, Markdown

from toad.app import ToadApp
from toad.acp import protocol
from toad.menus import MenuItem
from toad.pill import pill
from toad.widgets.prepared_markdown import PreparedConversationMarkdown
from toad.widgets.worker_static import WorkerStatic
from toad.layout import trim_trailing_margin
from textual.layout import WidgetPlacement

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


class ToolContent(containers.VerticalGroup):
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ToolCallItem(containers.HorizontalGroup):
    def compose(self) -> ComposeResult:
        yield Static(classes="icon")


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
            assert prepared.fallback is not None
            highlighted = Content.from_rich_text(prepared.fallback)
            yield TextContent(Content(self.patch, list(highlighted.spans)))
        else:
            mode = self.app.settings.get("diff.view", str)
            yield PatchDiffView(prepared.patch, prepared=prepared,
                                 split=mode == "split", auto_split=mode == "auto",
                                 wrap=self.app.settings.get("diff.wrap") == "wrap",
                                 annotations=self.app.settings.get("diff.annotations", bool))

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
        try:
            tool = self.query_ancestor(ToolCall)
        except NoMatches:
            tool = None
        if tool is not None and (not tool.expanded or (tool._auto_expanded and not tool._visible_in_window())):
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


class ToolCallHeader(Static):
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    ToolCallHeader {
        width: auto;
        max-width: 1fr;        
        &:hover {
            background: $panel;
        }
    }
    """


class ToolCall(containers.VerticalGroup):
    DEFAULT_CLASSES = "block"

    app = getters.app(ToadApp)
    has_content: var[bool] = var(False, toggle_class="-has-content")
    expanded: var[bool] = var(False, toggle_class="-expanded")
    tool_call: var[protocol.ToolCall | None] = var(None)

    def __init__(
        self,
        tool_call: protocol.ToolCall,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.set_reactive(ToolCall.tool_call, tool_call)
        super().__init__(id=id, classes=classes)
        self._content_lock = asyncio.Lock()
        self._rendered_content: list | None = None
        self._rendered_simple_text = False
        self._manual_expansion: bool | None = None
        self._awaiting_visible_content = False
        self._auto_expanded = False
        self._hydration_scheduled = False
        self._warm_patch_sources: tuple[str, ...] = ()
        self._warm_patch_theme: tuple[bool, bool] | None = None
        self._warm_patches: dict[str, PatchWarmup] = {}
        self._warm_patch_generation = 0
        self._warm_patch_worker: Worker[None] | None = None

    async def update_tool_call(self, tool_call: protocol.ToolCall) -> None:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self._update_metadata()
        header = self.query_one(ToolCallHeader)
        content = self.tool_call_header_content
        if header.content != content:
            header.update(content)
        await self._sync_content()

    def get_block_menu(self) -> Iterable[MenuItem]:
        if self.expanded:
            yield MenuItem("Collapse", "block.collapse", "x")
        else:
            yield MenuItem("Expand", "block.expand", "x")

    def action_collapse(self) -> None:
        self.set_expanded(False)

    def action_expand(self) -> None:
        self.set_expanded(True)

    def get_block_content(self, destination: str) -> str | None:
        return None

    def can_expand(self) -> bool:
        return self.has_content

    def expand_block(self) -> None:
        self.set_expanded(True)

    def collapse_block(self) -> None:
        self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        """Record explicit presentation intent separately from ACP status updates."""
        self._manual_expansion = expanded
        self._auto_expanded = False
        self.expanded = expanded
        if expanded:
            for diff in self.query(ToolCallDiff):
                diff.publish_if_ready()
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            return
        tool_id = (self.tool_call or {}).get("toolCallId")
        if isinstance(tool_id, str):
            conversation.remember_tool_expansion(tool_id, expanded)

    def is_block_expanded(self) -> bool:
        return self.expanded

    def compose(self) -> ComposeResult:
        self._update_metadata()
        yield ToolCallHeader(self.tool_call_header_content, markup=False).with_tooltip(
            "Expand to see full title"
        )
        yield ToolContent(id="tool-content")

    async def on_mount(self) -> None:
        from toad.widgets.conversation import Conversation

        self.watch(self.app, "theme", self._warm_theme_changed, init=False)
        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            tool_id = (self.tool_call or {}).get("toolCallId")
            if isinstance(tool_id, str):
                self._manual_expansion = conversation.tool_expansions.get(tool_id)
                if self._manual_expansion is not None:
                    self._auto_expanded = False
                    self.expanded = self._manual_expansion
        await self._sync_content()

    def _update_metadata(self) -> None:
        assert self.tool_call is not None
        self.set_class(self.tool_call.get("status") == "failed", "-failed")
        self.has_content = any(
            item.get("type") in {"content", "diff"}
            for item in self.tool_call.get("content") or []
        )
        self.check_expand()

    async def _sync_content(self) -> None:
        """Keep only expanded output in the DOM, serialized against rapid updates."""
        async with self._content_lock:
            body = self.query_one_optional("#tool-content", containers.VerticalGroup)
            if body is None:
                return
            content = (self.tool_call or {}).get("content") or []
            if (self.expanded and self._auto_expanded
                    and not self._visible_in_window() and not body.children):
                # Auto-expansion is presentation policy, not a requirement to
                # construct every rich diff and Read tree in hidden tabs or
                # far beyond the visible transcript. A Show event hydrates it
                # when this header first reaches the viewport.
                self._schedule_patch_warmup(content)
                if not self._awaiting_visible_content:
                    self._awaiting_visible_content = True
                    from toad.widgets.conversation import Window

                    try:
                        self.query_ancestor(Window).pending_tool_content.add(self)
                    except NoMatches:
                        pass
                    # Show can be dispatched before an on-mount content check;
                    # test the committed first layout once as well.
                    self.call_after_refresh(self._hydrate_visible_content)
                return
            self._awaiting_visible_content = False
            from toad.widgets.conversation import Window

            try:
                self.query_ancestor(Window).pending_tool_content.discard(self)
            except NoMatches:
                pass
            if not self.expanded:
                self._cancel_patch_warmup()
                if body.children:
                    await body.remove_children()
                self._rendered_content = None
                self._rendered_simple_text = False
            elif self._rendered_content != content:
                text = self._simple_text_payload(content)
                children = body.children
                retained = (children[0] if len(children) == 1 and type(children[0]) is TextContent else None)
                state = self.screen._select_state
                endpoint_selected = retained is not None and state is not None and (
                    state.start.content_widget is retained
                    or (state.end is not None and state.end.content_widget is retained)
                )
                if (self._rendered_simple_text and text is not None and retained is not None
                        and retained.text_selection is None and not endpoint_selected):
                    # Content values carry their own spans, so transitions between
                    # plain and ANSI output don't depend on the old markup flag.
                    rendered = (Content.from_rich_text(Text.from_ansi(text))
                                if "\x1b" in text else Content(text))
                    retained.update(rendered)
                else:
                    with self.app.batch_update():
                        await body.remove_children()
                        await body.mount_all(self._compose_content(content))
                self._rendered_simple_text = text is not None
                # ACP adapters may mutate the same payload on subsequent updates.
                self._rendered_content = deepcopy(content)

    def _schedule_patch_warmup(self, content: list[protocol.ToolCallContent]) -> None:
        # Decode only the same ACP resource branch used by _compose_content.
        patches: list[str] = []
        for item in content:
            match item:
                case {"type": "content", "content": {"type": "resource", "resource": {
                    "mimeType": "text/x-diff", "text": str(source),
                }}}:
                    patches.append(source)
        sources = tuple(dict.fromkeys(patches))
        theme = (self.app.current_theme.ansi, self.app.current_theme.dark)
        if sources == self._warm_patch_sources and theme == self._warm_patch_theme:
            return
        self._cancel_patch_warmup()
        self._warm_patch_sources, self._warm_patch_theme = sources, theme
        if sources:
            loop = asyncio.get_running_loop()
            self._warm_patches = {source: PatchWarmup(source, theme, loop.create_future()) for source in sources}
            self._warm_patch_worker = self.run_worker(
                self._warm_patch_data(self._warm_patch_generation, tuple(self._warm_patches.values())),
                group="hidden-patch-warmup", exclusive=True, exit_on_error=False,
            )

    async def _warm_patch_data(
        self, generation: int, entries: tuple[PatchWarmup, ...],
    ) -> None:
        from toad.render_tasks import PatchRenderTask

        # App-owned admission remains occupied even if this widget waiter is
        # cancelled. Visible jobs keep the renderer's other submission slots.
        try:
            for entry in entries:
                if generation != self._warm_patch_generation or not self.is_attached:
                    return
                prepared = await self.app.prepare_background(PatchRenderTask(entry.source, *entry.theme))
                if generation != self._warm_patch_generation or not self.is_attached:
                    return
                if not entry.result.done():
                    entry.result.set_result(prepared)
        except Exception as error:
            self.log.warning("Background diff preparation failed", error)
        finally:
            # A failed background attempt is a cache miss, not a lost foreground
            # result. The native visible preparation path can report/retry it.
            for entry in entries:
                if not entry.result.done():
                    entry.result.set_result(None)

    def _cancel_patch_warmup(self) -> None:
        self._warm_patch_generation += 1
        if self._warm_patch_worker is not None:
            self._warm_patch_worker.cancel()
            self._warm_patch_worker = None
        for entry in self._warm_patches.values():
            if not entry.result.done():
                entry.result.cancel()
        self._warm_patch_sources = ()
        self._warm_patch_theme = None
        self._warm_patches.clear()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        self._warm_theme_changed()

    def _warm_theme_changed(self) -> None:
        if self.is_mounted and self.is_attached and self._awaiting_visible_content and self.expanded:
            self._schedule_patch_warmup((self.tool_call or {}).get("content") or [])

    def _simple_text_payload(self, content: list[protocol.ToolCallContent]) -> str | None:
        """Recognize the single plain/ANSI branch of the ordinary renderer."""
        match content:
            case [{"type": "content", "content": {"type": "text", "text": str(text)}}]:
                pass
            case _:
                return None
        tool_call = self.tool_call or {}
        raw_input = tool_call.get("rawInput") or {}
        path = (raw_input.get("path") or raw_input.get("file_path") or raw_input.get("filePath")) if isinstance(raw_input, dict) else None
        if tool_call.get("kind") == "read" and isinstance(path, str):
            return None
        if "\x1b" not in text and ("```" in text or re.search(r"^#{1,6}\s.*$", text, re.MULTILINE)):
            return None
        return text

    async def on_show(self) -> None:
        self.hydrate_if_visible()

    def hydrate_if_visible(self) -> None:
        if (self._awaiting_visible_content and self.expanded and not self._hydration_scheduled
                and self._visible_in_window()):
            self._hydration_scheduled = True
            self.run_worker(self._hydrate_visible_content(), group="visible-content")

    async def _hydrate_visible_content(self) -> None:
        try:
            if (self.is_attached and self._awaiting_visible_content and self.expanded
                    and self._visible_in_window()):
                await self._sync_content()
        finally:
            self._hydration_scheduled = False

    def on_unmount(self) -> None:
        from toad.widgets.conversation import Window

        self._cancel_patch_warmup()
        try:
            self.query_ancestor(Window).pending_tool_content.discard(self)
        except NoMatches:
            pass

    def _visible_in_window(self) -> bool:
        from toad.widgets.conversation import Window

        if not self.is_attached or not self.screen.is_active:
            return False
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return False
        try:
            window = self.query_ancestor(Window)
        except NoMatches:
            return True
        region, _clip = geometry
        return region.overlaps(window.content_region)

    def check_expand(self) -> None:
        """Check if the tool call should auto-expand."""
        if self._manual_expansion is not None:
            return
        if not self.has_content:
            return
        tool_call = self.tool_call
        assert tool_call is not None
        if tool_call.get("kind", "") == "read":
            # Don't auto expand reads, as it can generate a lot of noise
            return
        tool_call_expand = self.app.settings.get("tools.expand", str, expand=False)
        status = tool_call.get("status")
        patches = [
            item["content"]["resource"]["text"]
            for item in tool_call.get("content") or []
            if item.get("type") == "content" and item.get("content", {}).get("type") == "resource"
            and item["content"].get("resource", {}).get("mimeType") == "text/x-diff"
            and isinstance(item["content"]["resource"].get("text"), str)
        ]
        if (patches and status == "completed" and tool_call_expand != "never"
                and sum(len(patch) for patch in patches) <= 16000
                and sum(patch.count("\n") for patch in patches) <= 200):
            self._auto_expanded = True
            self.expanded = True
            return
        if tool_call_expand == "always":
            self._auto_expanded = True
            self.expanded = True
        elif tool_call_expand != "never" and status is not None:
            if tool_call_expand == "success":
                self.expanded = status == "completed"
            elif tool_call_expand == "fail":
                self.expanded = status == "failed"
            elif tool_call_expand == "both":
                self.expanded = status in ("completed", "failed")
            self._auto_expanded = self.expanded

    @property
    def tool_call_header_content(self) -> Content:
        tool_call = self.tool_call
        assert tool_call is not None
        _kind = tool_call.get("kind", "tool")
        title = tool_call.get("title", "title")
        status = tool_call.get("status", "pending")

        expand_icon: Content = Content()
        if self.has_content:
            expand_icon = Content.from_markup(
                "[$text-secondary]▼ " if self.expanded else "[$text-secondary]▶ "
            )
        else:
            expand_icon = Content.from_markup(
                "[$text-secondary 30%]▼ "
                if self.expanded
                else "[$text-secondary 30%]▶ "
            )

        header = Content.assemble(expand_icon, "🔧 ", title)

        if status == "pending":
            header += Content.assemble(" ⌛")
        elif status == "in_progress":
            header += Content.assemble(
                " ",
                pill(
                    "running",
                    "$warning-muted",
                    "$warning",
                    filled=not self.app.theme.startswith("ansi-"),
                ),
            )
        elif status == "failed":
            header += Content.assemble(
                " ",
                pill(
                    "failed",
                    "$error-muted",
                    "$error",
                    filled=not self.app.theme.startswith("ansi-"),
                ),
            )
        elif status == "completed":
            header += Content.from_markup(" [$success]✔")
        return header

    async def watch_expanded(self) -> None:
        await self._sync_content()
        try:
            self.query_one(ToolCallHeader).update(self.tool_call_header_content)
        except NoMatches:
            pass
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            self.call_after_refresh(conversation.cursor.update_follow)

    @on(events.Click, "ToolCallHeader")
    def on_click_tool_call_header(self, event: events.Click) -> None:
        event.stop()
        if self.has_content:
            self.set_expanded(not self.expanded)
        else:
            self.app.bell()

    def _compose_content(
        self, tool_call_content: list[protocol.ToolCallContent]
    ) -> ComposeResult:
        def compose_content_block(
            content_block: protocol.ContentBlock,
        ) -> ComposeResult:
            match content_block:
                case {"type": "resource", "resource": {"mimeType": "text/x-diff", "text": patch}}:
                    theme = (self.app.current_theme.ansi, self.app.current_theme.dark)
                    warmup = self._warm_patches.get(patch) if self._warm_patch_theme == theme else None
                    yield ToolCallDiff(patch, warmup=warmup)
                # TODO: This may need updating
                # Docs claim this should be "plain" text
                # However, I have seen simple text, text with ansi escape sequences, and Markdown returned
                # I think this is a flaw in the spec.
                # For now I will attempt a heuristic to guess what the content actually contains
                # https://agentclientprotocol.com/protocol/schema#param-text
                case {"type": "text", "text": text}:
                    assert isinstance(text, str)
                    raw_input = (self.tool_call or {}).get("rawInput") or {}
                    path = (raw_input.get("path") or raw_input.get("file_path") or raw_input.get("filePath")) if isinstance(raw_input, dict) else None
                    if (self.tool_call or {}).get("kind") == "read" and isinstance(path, str):
                        yield WorkerStatic.code(text, filename=path, line_numbers=False,
                                                themed=True, filename_only=True)
                    elif "\x1b" in text:
                        parsed_ansi_text = Text.from_ansi(text)
                        yield TextContent(Content.from_rich_text(parsed_ansi_text))
                    elif "```" in text or re.search(
                        r"^#{1,6}\s.*$", text, re.MULTILINE
                    ):
                        yield MarkdownContent(text)
                    else:
                        yield TextContent(text, markup=False)

        for content in tool_call_content:
            match content:
                case {"type": "content", "content": sub_content}:
                    yield from compose_content_block(sub_content)
                case {
                    "type": "diff",
                    "path": path,
                    "oldText": old_text,
                    "newText": new_text,
                }:
                    from toad.widgets.diff_view import make_diff

                    yield (diff_view := make_diff(path, path, old_text, new_text))

                    if isinstance(self.app, ToadApp):
                        diff_view_setting = self.app.settings.get("diff.view", str)
                        diff_view.split = diff_view_setting == "split"
                        diff_view.auto_split = diff_view_setting == "auto"

                case {"type": "terminal", "terminalId": terminal_id}:
                    pass


if __name__ == "__main__":
    from textual.app import App, ComposeResult

    TOOL_CALL_READ: protocol.ToolCall = {
        "sessionUpdate": "tool_call",
        "toolCallId": "write_file-1759480341499",
        "status": "completed",
        "title": "Foo",
        "content": [
            {
                "type": "diff",
                "path": "fib.py",
                "oldText": "",
                "newText": 'def fibonacci(n):\n    """Generates the Fibonacci sequence up to n terms."""\n    a, b = 0, 1\n    for _ in range(n):\n        yield a\n        a, b = b, a + b\n\nif __name__ == "__main__":\n    for number in fibonacci(10):\n        print(number)\n',
            }
        ],
    }

    TOOL_CALL_CONTENT: protocol.ToolCall = {
        "sessionUpdate": "tool_call",
        "toolCallId": "run_shell_command-1759480356886",
        "status": "completed",
        "title": "Bar",
        "content": [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "0\n1\n1\n2\n3\n5\n8\n13\n21\n34",
                },
            }
        ],
    }

    TOOL_CALL_EMPTY: protocol.ToolCall = {
        "sessionUpdate": "tool_call",
        "toolCallId": "run_shell_command-1759480356886",
        "status": "completed",
        "title": "Bar",
        "content": [],
    }

    class ToolApp(App):
        def on_mount(self) -> None:
            self.theme = "dracula"

        def compose(self) -> ComposeResult:
            yield ToolCall(TOOL_CALL_READ)
            yield ToolCall(TOOL_CALL_CONTENT)
            yield ToolCall(TOOL_CALL_EMPTY)

    ToolApp().run()
