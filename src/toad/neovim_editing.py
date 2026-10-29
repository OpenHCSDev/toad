"""Real modal editing. Neovim owns the buffer, registers, undo and input grammar."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import cached_property
from importlib.resources import files
from itertools import count
from typing import TYPE_CHECKING, ClassVar
from weakref import ref

import msgpack
from agent_comms.child_process import AttachedChild, join_retirement
from textual.binding import Binding
from textual.cursor_shape import BlinkingBar, CursorShape, SteadyBlock
from textual.document._document import Location, Selection
from textual.document._editing import EditingFailure, EditingMode, VimMode
from textual.keys import key_to_character
from textual.message import Message

if TYPE_CHECKING:
    from textual.document._edit import Edit
    from textual.events import Key
    from textual.widgets import TextArea


class NeovimWireFailure(EditingFailure):
    """A child, transport or external Neovim protocol failure, not a Vim prefix."""


@dataclass(frozen=True)
class NeovimState:
    """Mode and blocking come only from the actual fast nvim_get_mode response."""

    code: str
    blocking: bool
    cursor: tuple[int, int]
    command_line: str
    regions: tuple[Selection, ...] = ()
    region_text: str = ""
    mode_name: ClassVar[str] = ""
    cursor_shape: ClassVar[CursorShape] = SteadyBlock()

    @property
    def label(self) -> str:
        return (self.mode_name or self.code.upper()) + (" (PENDING)" if self.blocking else "")

    @property
    def accepts_text(self) -> bool:
        return False

    @property
    def allows_application_commands(self) -> bool:
        return False

    @property
    def allows_history_navigation(self) -> bool:
        return False

    @classmethod
    def decode(cls, value: object, lines: tuple[str, ...], previous: NeovimState) -> NeovimState:
        if not isinstance(value, list) or len(value) != 4:
            raise NeovimWireFailure("Invalid Neovim editor state")
        cursor, command_line, regions, selected = value
        if not isinstance(command_line, str):
            raise NeovimWireFailure("Invalid Neovim command line")

        def location(position: object) -> tuple[int, int]:
            if not (isinstance(position, list) and len(position) == 2
                    and all(isinstance(n, int) for n in position)):
                raise NeovimWireFailure("Invalid Neovim byte position")
            row, column = position
            row = max(0, min(row - 1, len(lines) - 1))
            try:
                return row, len(lines[row].encode("utf-8")[:max(0, column - 1)].decode("utf-8"))
            except UnicodeDecodeError as error:
                raise NeovimWireFailure("Neovim supplied a split UTF-8 position") from error

        if not isinstance(regions, list) or not isinstance(selected, str):
            raise NeovimWireFailure("Invalid Neovim selected region")
        selections: list[Selection] = []
        for region in regions:
            if not (isinstance(region, list) and len(region) == 2
                    and all(isinstance(pos, list) and len(pos) == 4 for pos in region)):
                raise NeovimWireFailure("Invalid Neovim region position")
            start, end = region
            first, final = location(start[1:3]), location(end[1:3])
            selections.append(Selection(first, (final[0], final[1] + 1)))
        return cls.from_fields(previous.code, previous.blocking, location(cursor), command_line,
                               tuple(selections), selected)

    @classmethod
    def fast_mode(cls, value: object, previous: NeovimState) -> NeovimState:
        if not isinstance(value, dict) or not isinstance(value.get("mode"), str) or not isinstance(value.get("blocking"), bool):
            raise NeovimWireFailure("Invalid Neovim fast mode response")
        return cls.from_fields(value["mode"], value["blocking"], previous.cursor,
                               previous.command_line, previous.regions, previous.region_text)

    @classmethod
    def from_fields(cls, code: str, blocking: bool, cursor: tuple[int, int],
                    command_line: str, regions: tuple[Selection, ...], selected: str) -> NeovimState:
        args = code, blocking, cursor, command_line, regions, selected
        # The external Neovim taxonomy is decoded here, never from input keys.
        if code.startswith("i"):
            return InsertState(*args)
        if code == "n":
            return NormalState(*args)
        if code.startswith("no"):
            return OperatorState(*args)
        if code == "c":
            return CommandLineState(*args)
        if code in ("v", "s"):
            return VisualState(*args)
        if code in ("V", "S"):
            return LineVisualState(*args)
        if code in ("\x16", "\x13"):
            return BlockVisualState(*args)
        if code.startswith("R"):
            return ReplaceState(*args)
        return cls(*args)

    def selection(self) -> Selection:
        return Selection.cursor(self.cursor)

    def selection_for_line(self, row: int) -> Selection:
        return self.selection()

    def selected_text(self) -> str:
        return ""


class TextEntryState(NeovimState):
    cursor_shape = BlinkingBar()

    @property
    def accepts_text(self) -> bool:
        return not self.blocking


class HistoryState(NeovimState):
    @property
    def allows_history_navigation(self) -> bool:
        return not self.blocking


class ApplicationCommandState(NeovimState):
    @property
    def allows_application_commands(self) -> bool:
        return not self.blocking


class InsertState(TextEntryState, HistoryState):
    mode_name = "INSERT"


class NormalState(ApplicationCommandState, HistoryState):
    mode_name = "NORMAL"


class ReplaceState(TextEntryState):
    mode_name = "REPLACE"


class OperatorState(NeovimState):
    mode_name = "OPERATOR"


class CommandLineState(NeovimState):
    mode_name = "COMMAND"


class VisualState(NeovimState):
    mode_name = "VISUAL"

    def selection(self) -> Selection:
        if not self.regions:
            return super().selection()
        return Selection(self.regions[0].start, self.regions[-1].end)

    def selection_for_line(self, row: int) -> Selection:
        return next((region for region in self.regions if region.start[0] == row),
                    Selection.cursor(self.cursor))

    def selected_text(self) -> str:
        return self.region_text


class LineVisualState(VisualState):
    mode_name = "VISUAL LINE"


class BlockVisualState(VisualState):
    mode_name = "VISUAL BLOCK"


class NeovimRequest(ABC):
    """One admitted wire request and its eventual reply; sending never waits for it."""

    _identities = count(1)

    def __init__(self) -> None:
        self.identity = next(self._identities)
        self.reply: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self.sent: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    @property
    @abstractmethod
    def method(self) -> str: ...

    @property
    @abstractmethod
    def arguments(self) -> Sequence[object]: ...

    async def send(self, child: AttachedChild) -> None:
        try:
            await child.write(msgpack.packb(
                [0, self.identity, self.method, list(self.arguments)], use_bin_type=True))
            self.sent.set_result(None)
        except OSError as error:
            raise NeovimWireFailure(str(error)) from error

    def resolve(self, value: object) -> None:
        self.reply.set_result(value)

    async def result(self) -> object:
        await asyncio.shield(self.sent)
        return await self.wait_reply()

    async def wait_reply(self) -> object:
        return await asyncio.shield(self.reply)


class NeovimFastRequest(NeovimRequest):
    async def wait_reply(self) -> object:
        # Only a fast API reply has a wire timeout. A deferred operation may
        # legitimately await an operand; that is not a broken child.
        try:
            async with asyncio.timeout(5):
                return await super().wait_reply()
        except TimeoutError as error:
            raise NeovimWireFailure(f"Neovim fast request {self.method} did not reply") from error


class NeovimModeRequest(NeovimFastRequest):
    method = "nvim_get_mode"
    arguments = ()


class NeovimCall(NeovimRequest):
    def __init__(self, method: str, arguments: Sequence[object]) -> None:
        super().__init__()
        self._method, self._arguments = method, arguments

    @property
    def method(self) -> str:
        return self._method

    @property
    def arguments(self) -> Sequence[object]:
        return self._arguments


class NeovimInput(NeovimFastRequest):
    method = "nvim_input"

    def __init__(self, keys: str) -> None:
        super().__init__()
        self.keys = keys

    @property
    def arguments(self) -> Sequence[object]:
        return (self.keys,)

    def resolve(self, value: object) -> None:
        if not isinstance(value, int) or value != len(self.keys.encode("utf-8")):
            raise NeovimWireFailure("Neovim did not accept the complete key; it was not replayed")
        super().resolve(value)


class NeovimChange(ABC):
    @abstractmethod
    def apply(self, editor: TextArea) -> None: ...


@dataclass(frozen=True)
class NeovimLineChange(NeovimChange):
    first: int
    last: int
    lines: tuple[str, ...]

    def apply(self, editor: TextArea) -> None:
        editor.apply_engine_lines(self.first, self.last, self.lines)


@dataclass(frozen=True)
class NeovimBufferTransfer(NeovimChange):
    lines: tuple[str, ...]

    def apply(self, editor: TextArea) -> None:
        editor.apply_engine_text("\n".join(self.lines))


@dataclass(frozen=True)
class NeovimSnapshot:
    owner: NeovimEditing
    lines: tuple[str, ...]
    state: NeovimState
    changes: tuple[NeovimChange, ...] = ()

    def apply(self, editor: TextArea) -> None:
        if (editor.editing_mode is not self.owner or self.owner._receiver() is not editor
                or not editor.is_attached or self is not self.owner.snapshot
                or self is self.owner._rendered):
            return
        for change in self.changes:
            change.apply(editor)
        del self.owner._changes[:len(self.changes)]
        self.owner._rendered = self
        editor.apply_engine_selection(Selection.cursor(self.state.cursor))
        editor._line_cache.clear()
        editor.record_cursor_width()
        editor.show_editing_mode(self.owner)
        editor.refresh_bindings()
        editor.refresh()


class NeovimUpdated(Message):
    def __init__(self, snapshot: NeovimSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot


class NeovimEditing(VimMode):
    """One editor resource, one admission queue; Neovim schedules actual execution."""

    initial_keys = ""

    def __init__(self) -> None:
        self._receiver: Callable[[], TextArea | None] = lambda: None
        self._pending: dict[int, NeovimRequest] = {}
        self._outgoing: asyncio.Queue[NeovimRequest] = asyncio.Queue()
        self._lines: tuple[str, ...] = ("",)
        self.snapshot = NeovimSnapshot(self, self._lines,
            NeovimState("NEOVIM STARTING", False, (0, 0), ""))
        self._failure: EditingFailure | None = None
        self._changes: list[NeovimChange] = []
        self._rendered: NeovimSnapshot | None = None
        self._boundaries: list[Binding] = []

    @property
    def label(self) -> str:
        if self._failure is not None:
            return "NEOVIM FAILED — draft preserved"
        state = self.snapshot.state
        return f"{state.label} {state.command_line}".rstrip()

    @property
    def accepts_text(self) -> bool:
        return self._failure is None and self.snapshot.state.accepts_text

    @property
    def allows_application_commands(self) -> bool:
        return self._failure is None and self.snapshot.state.allows_application_commands

    @property
    def allows_history_navigation(self) -> bool:
        return self._failure is None and self.snapshot.state.allows_history_navigation

    @property
    def cursor_shape(self) -> CursorShape:
        return self.snapshot.state.cursor_shape

    @property
    def binding_mode(self) -> type[EditingMode]:
        return type(self)

    @cached_property
    def _started(self) -> asyncio.Task[None]:
        editor = self._receiver()
        if editor is None:
            raise RuntimeError("Neovim requires an attached editor")
        self._initial_lines = tuple(editor.document.lines)
        self._initial_selection = editor.selection
        self._child_ready: asyncio.Future[AttachedChild] = asyncio.get_running_loop().create_future()
        self._lifetime = editor.app.run_worker(self._run(), name="Neovim editor", exit_on_error=True)
        task = asyncio.create_task(self._start())
        task.add_done_callback(self._observe_failure)
        return task

    def attach(self, editor: TextArea) -> None:
        previous = self._receiver()
        self._receiver = ref(editor)
        if previous is not editor:
            self._rendered = None
            self.snapshot = NeovimSnapshot(self, self._lines, self.snapshot.state, tuple(self._changes))
        started = self._started
        if started.done() and not started.cancelled() and started.exception() is None:
            self.snapshot.apply(editor)

    def resume(self, editor: TextArea) -> None:
        pass

    def suspend(self, editor: TextArea) -> None:
        pass

    def capture(self, editor: TextArea) -> NeovimEditing:
        self._receiver = lambda: None
        return self

    async def unmount(self, editor: TextArea) -> None:
        if self._receiver() is editor:
            await self.close()

    async def close(self) -> None:
        started = self._started
        self._receiver = lambda: None
        started.cancel()
        self._lifetime.cancel()
        await join_retirement(asyncio.create_task(self._join()))

    async def _join(self) -> None:
        await asyncio.gather(self._started, return_exceptions=True)
        try:
            await self._lifetime.wait()
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        try:
            async with AsyncExitStack() as cleanup:
                async def acquire_child() -> AttachedChild:
                    child = await AttachedChild.start(("nvim", "--embed", "--clean", "-n"))
                    cleanup.push_async_callback(child.stop)
                    return child

                spawn = asyncio.create_task(acquire_child())
                try:
                    child = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    await join_retirement(spawn)
                    raise
                self._child = child
                if self._child_ready.cancelled():
                    return
                self._child_ready.set_result(child)
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(self._write_admitted())
                    await self._read(child)
        except* (EditingFailure, OSError, msgpack.UnpackException, msgpack.FormatError,
                 msgpack.StackError, msgpack.BufferFull, UnicodeDecodeError) as errors:
            self._fail(NeovimWireFailure("; ".join(str(error) for error in errors.exceptions)))
        finally:
            error = self._failure or EditingFailure("Neovim editor closed; input was not replayed")
            if not self._child_ready.done():
                self._child_ready.set_exception(error)
            for request in self._pending.values():
                if not request.sent.done():
                    request.sent.set_exception(error)
                if not request.reply.done():
                    request.reply.set_exception(error)
            self._pending.clear()

    async def _read(self, child: AttachedChild) -> None:
        assert child.stdout is not None
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False, max_buffer_size=16 * 1024 * 1024)
        while chunk := await child.stdout.read(65536):
            unpacker.feed(chunk)
            for message in unpacker:
                await self._receive(message)
        raise NeovimWireFailure(f"Neovim exited: {await child.stderr_tail()}")

    async def _write_admitted(self) -> None:
        await self._started
        while True:
            request = await self._outgoing.get()
            # A deferred edit can need a later operand key. Await only the write,
            # never its response, before admitting the next request to Neovim.
            await request.send(self._child)

    def _register(self, request: NeovimRequest) -> None:
        request.reply.add_done_callback(self._observe_failure)
        request.sent.add_done_callback(self._observe_failure)
        if self._failure is not None:
            raise self._failure
        self._pending[request.identity] = request

    async def _bootstrap(self, request: NeovimRequest) -> object:
        """Acquisition owns the child until its UI/buffer integration is installed."""
        self._register(request)
        await request.send(self._child)
        return await request.result()

    def _admit(self, request: NeovimRequest) -> asyncio.Task[object]:
        try:
            self._register(request)
        except EditingFailure as error:
            request.sent.set_exception(error)
            request.reply.set_exception(error)
        else:
            self._outgoing.put_nowait(request)
        result = asyncio.create_task(request.result())
        result.add_done_callback(self._observe_failure)
        return result

    def _call(self, method: str, arguments: Sequence[object]) -> asyncio.Future[object]:
        return self._admit(NeovimCall(method, arguments))

    def _input(self, keys: str) -> asyncio.Future[object]:
        return self._admit(NeovimInput(keys))

    async def _start(self) -> None:
        await self._child_ready
        editor = self._receiver()
        width = max(1, editor.wrap_width) if editor is not None else 80
        height = max(3, editor.content_size.height + 2) if editor is not None else 24
        await self._bootstrap(NeovimCall("nvim_ui_attach", [width, height,
            {"ext_linegrid": True, "ext_cmdline": True, "ext_messages": True}]))
        self._lines = self._initial_lines
        undo_levels = await self._bootstrap(NeovimCall("nvim_get_option_value", ["undolevels", {"buf": 0}]))
        await self._bootstrap(NeovimCall("nvim_set_option_value", ["undolevels", -1, {"buf": 0}]))
        await self._bootstrap(NeovimCall("nvim_buf_set_lines", [0, 0, -1, True, list(self._lines)]))
        await self._bootstrap(NeovimCall("nvim_set_option_value", ["undolevels", undo_levels, {"buf": 0}]))
        initial_cursor = self._initial_selection.end
        row, column = initial_cursor
        await self._bootstrap(NeovimCall("nvim_win_set_cursor", [0,
            [row + 1, len(self._lines[row][:column].encode("utf-8"))]]))
        script = files("toad").joinpath("neovim_editing.lua").read_text()
        mappings: list[list[object]] = []
        if editor is not None:
            for key, binding in editor.binding_map(type(self)):
                for spelling, native in binding.declared_key.input_bindings(key):
                    index = len(self._boundaries)
                    self._boundaries.append(binding)
                    mappings.append([self.input_code(spelling), self.input_code(native), index])
        await self._bootstrap(NeovimCall("nvim_exec_lua", [script, [mappings]]))
        if editor is not None:
            await self._bootstrap(NeovimCall("nvim_set_option_value", ["tabstop", editor.indent_width, {}]))
        if self.initial_keys:
            await self._bootstrap(NeovimInput(self.initial_keys))
            await self._bootstrap(NeovimCall("nvim_exec_lua", ["return ToadEditor.cursor(...)", [initial_cursor]]))
        raw = await self._bootstrap(NeovimCall("nvim_exec_lua", ["return ToadEditor.state()", []]))
        self._accept_state(raw)
        self._accept_mode(await self._bootstrap(NeovimModeRequest()))

    async def _receive(self, message: object) -> None:
        """The only MessagePack-RPC decoder; these tests concern foreign wire data."""
        if not isinstance(message, list) or not message or not isinstance(message[0], int):
            raise NeovimWireFailure("Invalid Neovim RPC message")
        if message[0] == 1 and len(message) == 4:
            _, identity, error, result = message
            if not isinstance(identity, int) or identity not in self._pending:
                raise NeovimWireFailure("Unexpected Neovim RPC response")
            request = self._pending[identity]
            if error is None:
                request.resolve(result)
            else:
                request.reply.set_exception(NeovimWireFailure(f"Neovim {request.method}: {error}"))
            del self._pending[identity]
        elif message[0] == 2 and len(message) == 3:
            _, method, arguments = message
            if method == "nvim_buf_lines_event":
                if not isinstance(arguments, list) or len(arguments) != 6:
                    raise NeovimWireFailure("Invalid Neovim buffer notification")
                _, tick, first, last, lines, _more = arguments
                if not (isinstance(first, int) and isinstance(last, int) and isinstance(lines, list)
                        and all(isinstance(line, str) for line in lines)):
                    raise NeovimWireFailure("Invalid Neovim line update")
                if tick is not None:
                    if last == -1:
                        self._lines = tuple(lines)
                        self._changes.append(NeovimBufferTransfer(self._lines))
                    else:
                        self._lines = self._lines[:first] + tuple(lines) + self._lines[last:]
                        self._changes.append(NeovimLineChange(first, last, tuple(lines)))
            elif method == "toad_editor_state":
                self._accept_state(arguments)
                self._refresh_mode()
        elif message[0] == 0 and len(message) == 4:
            _, identity, method, arguments = message
            if (method != "toad_cursor_boundary" or not isinstance(arguments, list)
                    or len(arguments) != 1 or not isinstance(arguments[0], int)
                    or not 0 <= arguments[0] < len(self._boundaries)):
                await self._child.write(msgpack.packb([1, identity, "Unsupported Neovim host request", None]))
                return
            editor = self._receiver()
            handled = (editor is not None and editor.is_attached
                       and self._boundaries[arguments[0]].engine_boundary(editor))
            await self._child.write(msgpack.packb([1, identity, None, handled]))
        else:
            raise NeovimWireFailure("Invalid Neovim RPC envelope")

    def _publish(self, state: NeovimState) -> None:
        self.snapshot = NeovimSnapshot(self, self._lines, state, tuple(self._changes))
        if (editor := self._receiver()) is not None and editor.is_attached:
            editor.post_message(NeovimUpdated(self.snapshot))

    def _accept_state(self, raw: object) -> None:
        self._publish(NeovimState.decode(raw, self._lines, self.snapshot.state))

    def _accept_mode(self, raw: object) -> None:
        self._publish(NeovimState.fast_mode(raw, self.snapshot.state))

    def _mode_reply(self, reply: asyncio.Future[object]) -> None:
        try:
            self._accept_mode(reply.result())
        except asyncio.CancelledError:
            pass
        except EditingFailure as error:
            self._fail(error)

    def _refresh_mode(self) -> asyncio.Future[object]:
        reply = self._admit(NeovimModeRequest())
        reply.add_done_callback(self._mode_reply)
        return reply

    def _observe_failure[Result](self, result: asyncio.Future[Result]) -> None:
        try:
            result.result()
        except asyncio.CancelledError:
            pass
        except EditingFailure as error:
            self._fail(error)

    def _fail(self, error: EditingFailure) -> None:
        if self._failure is None:
            self._failure = error
            if (editor := self._receiver()) is not None:
                editor.notify(f"{error}. The displayed draft is preserved. Input was not replayed.",
                              title="Neovim editing failed", severity="error", timeout=0)
                editor.show_editing_mode(self)

    async def finish(self, editor: TextArea) -> bool:
        """Explicit profile handoff asks Neovim itself to cancel pending input."""
        await self._input("<Esc>")
        return await self.flush(editor)

    async def flush(self, editor: TextArea) -> bool:
        """Refuse pending input before a deferred read; never time out a Vim prefix."""
        await self.acknowledge(editor)
        if self.snapshot.state.blocking:
            return False
        raw = await self._call("nvim_exec_lua", ["return ToadEditor.state()", []])
        self._accept_state(raw)
        self.snapshot.apply(editor)
        return True

    async def acknowledge(self, editor: TextArea) -> None:
        await self._refresh_mode()
        self.snapshot.apply(editor)

    async def prepare_input(self, editor: TextArea) -> bool:
        finished: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        async def ready() -> None:
            if editor.editing_mode is not self:
                finished.set_result(True)
                return
            try:
                await self.acknowledge(editor)
            except EditingFailure:
                finished.set_result(False)
            else:
                finished.set_result(True)

        if not editor.call_later(ready):
            return False
        return await finished

    async def handle_key(self, editor: TextArea, event: Key) -> bool:
        try:
            await self._input(self.input_code(event.key, event.character))
        except EditingFailure:
            pass  # A real child/wire failure has been reported; never replay input.
        return True

    @staticmethod
    def input_code(key: str, character: str | None = None) -> str:
        """Textual's foreign key vocabulary enters Neovim at this boundary."""
        *modifiers, name = key.split("+")
        literal = character or key_to_character(name)
        if not modifiers and literal is not None and literal.isprintable():
            return literal.replace("<", "<LT>")
        names = {"enter": "CR", "escape": "Esc", "backspace": "BS", "delete": "Del",
                 "pageup": "PageUp", "pagedown": "PageDown", "space": "Space"}
        prefixes = {"ctrl": "C", "shift": "S", "alt": "A", "meta": "M", "super": "D"}
        base = literal if literal is not None and literal.isprintable() else names.get(name, name)
        base = "LT" if base == "<" else base
        return "<" + "-".join([*(prefixes[part] for part in modifiers), base]) + ">"

    def resize(self, editor: TextArea) -> None:
        self._call("nvim_ui_try_resize", [max(1, editor.wrap_width), max(3, editor.content_size.height + 2)])

    def enter_text(self, editor: TextArea) -> None:
        self._input("<Esc>i")

    def load_text(self, editor: TextArea, text: str) -> None:
        self._call("nvim_exec_lua", ["return ToadEditor.load(...)", [text]])

    def edit(self, editor: TextArea, edit: Edit) -> None:
        self._call("nvim_exec_lua", ["return ToadEditor.replace(...)",
            [edit.top, edit.bottom, edit.text.split("\n"), edit.maintain_selection_offset]])

    def insert(self, editor: TextArea, text: str, location: Location | None, maintain_selection_offset: bool) -> None:
        self._call("nvim_exec_lua", ["return ToadEditor.insert(...)",
            [text.split("\n"), location, maintain_selection_offset]])

    def clear(self, editor: TextArea) -> None:
        self.load_text(editor, "")

    def move_to_end(self, editor: TextArea) -> None:
        self._call("nvim_exec_lua", ["return ToadEditor.cursor_end()", []])

    def paste(self, editor: TextArea, text: str) -> None:
        self._call("nvim_paste", [text, True, -1])

    def undo(self, editor: TextArea) -> None:
        self._call("nvim_command", ["undo"])

    def redo(self, editor: TextArea) -> None:
        self._call("nvim_command", ["redo"])

    def request_selection(self, editor: TextArea, selection: Selection) -> Selection:
        if not selection.is_empty:
            self._input("<Esc>")
            self._call("nvim_exec_lua", ["return ToadEditor.select(...)", sorted(selection)])
        elif selection.end != self.snapshot.state.cursor:
            self._call("nvim_exec_lua", ["return ToadEditor.cursor(...)", [selection.end]])
        return editor.selection

    def selection_range(self, editor: TextArea) -> Selection:
        return self.snapshot.state.selection()

    def selection_for_line(self, editor: TextArea, row: int) -> Selection:
        return self.snapshot.state.selection_for_line(row)

    def selected_text(self, editor: TextArea) -> str:
        return self.snapshot.state.selected_text()
