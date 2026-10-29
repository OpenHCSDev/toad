"""Real modal editing. Neovim owns the buffer, registers, undo and input grammar."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import cached_property
from importlib.resources import files
from typing import TYPE_CHECKING
from weakref import ref

import msgpack
from agent_comms.child_process import AttachedChild, join_retirement
from textual.binding import Binding
from textual.cursor_shape import BlinkingBar, SteadyBlock
from textual.document._document import Selection
from textual.document._editing import VimMode
from textual.message import Message

if TYPE_CHECKING:
    from textual.document._edit import Edit
    from textual.events import Key
    from textual.widgets import TextArea


@dataclass(frozen=True)
class NeovimState:
    """Decoded external state, never inferred from the last key."""

    code: str
    cursor: tuple[int, int]
    anchor: tuple[int, int]
    command_line: str
    accepts_text = False
    allows_application_commands = False
    allows_history_navigation = False
    cursor_shape = SteadyBlock()

    @property
    def label(self) -> str:
        return self.code.upper()

    @classmethod
    def decode(cls, value: object, lines: tuple[str, ...]) -> NeovimState:
        if not isinstance(value, list) or len(value) != 6:
            raise ValueError("Invalid Neovim editor state")
        cursor, anchor, code, state, count, command_line = value
        if not (isinstance(code, str) and isinstance(state, str)
                and isinstance(count, int) and isinstance(command_line, str)):
            raise ValueError("Invalid Neovim mode state")

        def location(position: object) -> tuple[int, int]:
            if not (isinstance(position, list) and len(position) == 2
                    and all(isinstance(n, int) for n in position)):
                raise ValueError("Invalid Neovim byte position")
            row, column = position
            row = max(0, min(row - 1, len(lines) - 1))
            return row, len(lines[row].encode("utf-8")[:max(0, column - 1)].decode("utf-8"))

        args = code, location(cursor), location(anchor), command_line
        # This is the external Neovim taxonomy boundary, not a key interpreter.
        if code.startswith("i"):
            return InsertState(*args)
        if code == "n" and count == 0 and not any(flag in state for flag in "omS"):
            return NormalState(*args)
        if code == "v":
            return VisualState(*args)
        if code == "V":
            return LineVisualState(*args)
        if code == "\x16":
            return BlockVisualState(*args)
        if code.startswith("R"):
            return ReplaceState(*args)
        return cls(*args)

    def selection(self, lines: tuple[str, ...]) -> Selection:
        return Selection.cursor(self.cursor)

    def selection_for_line(self, lines: tuple[str, ...], row: int) -> Selection:
        return self.selection(lines)


class InsertState(NeovimState):
    label = "INSERT"
    accepts_text = True
    allows_history_navigation = True
    cursor_shape = BlinkingBar()


class NormalState(NeovimState):
    label = "NORMAL"
    allows_application_commands = True
    allows_history_navigation = True


class ReplaceState(NeovimState):
    label = "REPLACE"
    accepts_text = True
    cursor_shape = BlinkingBar()


class VisualState(NeovimState):
    label = "VISUAL"

    def selection(self, lines: tuple[str, ...]) -> Selection:
        start, end = sorted((self.anchor, self.cursor))
        return Selection(start, (end[0], min(len(lines[end[0]]), end[1] + 1)))


class LineVisualState(VisualState):
    label = "VISUAL LINE"

    def selection(self, lines: tuple[str, ...]) -> Selection:
        start, end = sorted((self.anchor, self.cursor))
        return Selection((start[0], 0), (end[0], len(lines[end[0]])))


class BlockVisualState(VisualState):
    label = "VISUAL BLOCK"

    def selection_for_line(self, lines: tuple[str, ...], row: int) -> Selection:
        top, bottom = sorted((self.anchor[0], self.cursor[0]))
        left, right = sorted((self.anchor[1], self.cursor[1]))
        if top <= row <= bottom:
            return Selection((row, left), (row, right + 1))
        return Selection.cursor(self.cursor)


@dataclass(frozen=True)
class NeovimSnapshot:
    owner: NeovimEditing
    lines: tuple[str, ...]
    state: NeovimState

    def apply(self, editor: TextArea) -> None:
        if editor.editing_mode is not self.owner or self is not self.owner.snapshot:
            return
        text = "\n".join(self.lines)
        if editor.text != text:
            # A derived rendering document has no independently writable undo stack.
            editor.history.clear()
            editor._set_document(text, editor.language)
            editor.post_message(editor.Changed(editor))
            editor.update_suggestion()
        editor.selection = Selection.cursor(self.state.cursor)
        editor._line_cache.clear()
        editor.record_cursor_width()
        editor.show_editing_mode(self.owner)
        editor.refresh_bindings()
        editor.refresh()


class NeovimUpdated(Message):
    """One immutable engine result enters the existing widget message loop."""

    def __init__(self, snapshot: NeovimSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot


class NeovimEditing(VimMode):
    """One lazy embedded child per editor resource, with serialized asynchronous RPC."""

    initial_keys = ""

    def __init__(self) -> None:
        self._receiver: ref[TextArea] = lambda: None
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._request_id = 0
        self._lines: tuple[str, ...] = ("",)
        self.snapshot = NeovimSnapshot(self, self._lines,
            NeovimState("NEOVIM STARTING", (0, 0), (0, 0), ""))
        self._failure: Exception | None = None

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
        return self.snapshot.state.allows_history_navigation

    @property
    def cursor_shape(self):
        return self.snapshot.state.cursor_shape

    @property
    def binding_mode(self):
        return type(self)

    @cached_property
    def _started(self) -> asyncio.Task[None]:
        editor = self._receiver()
        if editor is None:
            raise RuntimeError("Neovim requires an attached editor")
        self._initial_text = editor.text
        self._initial_selection = editor.selection
        self._child_ready = asyncio.get_running_loop().create_future()
        self._tail = asyncio.get_running_loop().create_future()
        self._tail.set_result(None)
        self._lifetime = editor.app.run_worker(self._run(), name="Neovim editor", exit_on_error=False)
        return asyncio.create_task(self._start())

    def attach(self, editor: TextArea) -> None:
        self._receiver = ref(editor)
        # Starting is lazy: Standard never starts a Neovim process.
        started = self._started
        started.add_done_callback(self._observe_failure)
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
        if "_started" not in self.__dict__:
            return
        self._receiver = lambda: None
        self._lifetime.cancel()
        await join_retirement(asyncio.create_task(self._join()))

    async def _join(self) -> None:
        await asyncio.gather(self._started, self._tail, return_exceptions=True)
        try:
            await self._lifetime.wait()
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        """The existing child owner handles identity, stderr and process-group teardown."""
        try:
            async with AsyncExitStack() as cleanup:
                spawn = asyncio.create_task(AttachedChild.start(("nvim", "--embed", "--clean", "-n")))
                try:
                    child = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    child = await join_retirement(spawn)
                    cleanup.push_async_callback(child.stop)
                    raise
                cleanup.push_async_callback(child.stop)
                self._child = child
                self._child_ready.set_result(child)
                assert child.stdout is not None
                unpacker = msgpack.Unpacker(raw=False, strict_map_key=False, max_buffer_size=16 * 1024 * 1024)
                while chunk := await child.stdout.read(65536):
                    unpacker.feed(chunk)
                    for message in unpacker:
                        await self._receive(message)
                raise RuntimeError(f"Neovim exited: {await child.stderr_tail()}")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail(error)
        finally:
            error = self._failure or RuntimeError("Neovim editor closed; input was not replayed")
            if not self._child_ready.done():
                self._child_ready.set_exception(error)
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(error)

    async def _start(self) -> None:
        await self._child_ready
        await self._rpc("nvim_ui_attach", [80, 24, {"ext_linegrid": True, "ext_cmdline": True, "ext_messages": True}])
        self._lines = tuple(self._initial_text.split("\n"))
        await self._rpc("nvim_buf_set_lines", [0, 0, -1, True, list(self._lines)])
        await self._rpc("nvim_win_set_cursor", [0, self._byte_cursor(self._initial_selection.end)])
        await self._rpc("nvim_buf_attach", [0, True, {}])
        script = files("toad").joinpath("neovim_editing.lua").read_text()
        editor = self._receiver()
        mappings: list[list[str]] = []
        if editor is not None:
            for key, binding in editor.binding_map(type(self)):
                for spelling, native in binding.declared_key.input_bindings(key):
                    mappings.append([self.input_code(spelling), self.input_code(native), native])
        await self._rpc("nvim_exec_lua", [script, [mappings]])
        if self.initial_keys:
            await self._rpc("nvim_input", [self.initial_keys])
        await self._snapshot()

    async def _rpc(self, method: str, arguments: list[object]) -> object:
        if self._failure is not None:
            raise self._failure
        self._request_id += 1
        identity = self._request_id
        future = self._pending[identity] = asyncio.get_running_loop().create_future()
        try:
            await self._child.write(msgpack.packb([0, identity, method, arguments], use_bin_type=True))
            async with asyncio.timeout(5):
                return await future
        finally:
            self._pending.pop(identity, None)

    async def _receive(self, message: object) -> None:
        """Decode MessagePack-RPC once. All type tests below concern foreign wire data."""
        if not isinstance(message, list) or not message or not isinstance(message[0], int):
            raise ValueError("Invalid Neovim RPC message")
        if message[0] == 1 and len(message) == 4:
            _, identity, error, result = message
            if not isinstance(identity, int) or identity not in self._pending:
                raise ValueError("Unexpected Neovim RPC response")
            future = self._pending[identity]
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(RuntimeError(f"Neovim RPC failed: {error}"))
        elif message[0] == 2 and len(message) == 3:
            _, method, arguments = message
            if method == "nvim_buf_lines_event":
                if not isinstance(arguments, list) or len(arguments) != 6:
                    raise ValueError("Invalid Neovim buffer notification")
                _, tick, first, last, lines, _more = arguments
                if not (isinstance(first, int) and isinstance(last, int) and isinstance(lines, list)
                        and all(isinstance(line, str) for line in lines)):
                    raise ValueError("Invalid Neovim line update")
                if tick is not None:
                    stop = len(self._lines) if last == -1 else last
                    self._lines = self._lines[:first] + tuple(lines) + self._lines[stop:]
            elif method == "toad_editor_state":
                state = NeovimState.decode(arguments, self._lines)
                self.snapshot = NeovimSnapshot(self, self._lines, state)
                if (editor := self._receiver()) is not None and editor.is_attached:
                    editor.post_message(NeovimUpdated(self.snapshot))
            # Grid data is deliberately not scraped. Text comes from buffer events.
        elif message[0] == 0 and len(message) == 4:
            _, identity, method, arguments = message
            if method != "toad_cursor_boundary" or not isinstance(arguments, list) or len(arguments) != 1 or not isinstance(arguments[0], str):
                await self._child.write(msgpack.packb([1, identity, "Unsupported Neovim host request", None]))
                return
            editor = self._receiver()
            handled = editor is not None and editor.is_attached and editor.before_engine_input(arguments[0])
            await self._child.write(msgpack.packb([1, identity, None, handled]))
        else:
            raise ValueError("Invalid Neovim RPC envelope")

    def _byte_cursor(self, location: tuple[int, int]) -> list[int]:
        row, column = location
        row = max(0, min(row, len(self._lines) - 1))
        return [row + 1, len(self._lines[row][:column].encode("utf-8"))]

    async def _snapshot(self) -> None:
        raw = await self._rpc("nvim_eval", ["[getpos('.')[1:2],getpos('v')[1:2],mode(1),state(),v:count,getcmdline()]"])
        self.snapshot = NeovimSnapshot(self, self._lines, NeovimState.decode(raw, self._lines))
        if (editor := self._receiver()) is not None and editor.is_attached:
            editor.post_message(NeovimUpdated(self.snapshot))

    def _enqueue(self, operation: Callable[[], Awaitable[object]]) -> asyncio.Task[None]:
        previous = self._tail

        async def run() -> None:
            await self._started
            await previous
            await operation()
            await self._snapshot()

        task = asyncio.create_task(run())
        self._tail = task
        task.add_done_callback(self._observe_failure)
        return task

    def _observe_failure(self, task: asyncio.Future[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self._fail(error)

    def _fail(self, error: Exception) -> None:
        if self._failure is None:
            self._failure = error
            if (editor := self._receiver()) is not None:
                editor.notify(f"{error}. The displayed draft is preserved. Input was not replayed.",
                              title="Neovim editing failed", severity="error", timeout=0)
                editor.show_editing_mode(self)

    async def flush(self, editor: TextArea) -> None:
        await self._started
        await self._tail
        if self._failure is not None:
            raise self._failure
        self.snapshot.apply(editor)

    async def prepare_input(self, editor: TextArea) -> None:
        finished = asyncio.get_running_loop().create_future()

        async def ready() -> None:
            try:
                await self.flush(editor)
            except Exception as error:
                finished.set_exception(error)
            else:
                finished.set_result(None)

        editor.call_later(ready)
        await finished

    async def handle_key(self, editor: TextArea, event: Key) -> bool:
        await self._enqueue(lambda: self._rpc("nvim_input", [self.input_code(event.key, event.character)]))
        self.snapshot.apply(editor)
        return True

    @staticmethod
    def input_code(key: str, character: str | None = None) -> str:
        """Textual's external key vocabulary enters Neovim at this one boundary."""
        if character is not None and character.isprintable():
            return character.replace("<", "<LT>")
        if len(key) == 1:
            return key.replace("<", "<LT>")
        *modifiers, name = key.split("+")
        names = {"enter": "CR", "escape": "Esc", "backspace": "BS", "delete": "Del",
                 "pageup": "PageUp", "pagedown": "PageDown", "space": "Space"}
        prefixes = {"ctrl": "C", "shift": "S", "alt": "A", "meta": "M", "super": "D"}
        return "<" + "-".join([*(prefixes[part] for part in modifiers), names.get(name, name)]) + ">"

    def enter_text(self, editor: TextArea) -> None:
        self._enqueue(lambda: self._rpc("nvim_input", ["<Esc>i"]))

    def load_text(self, editor: TextArea, text: str) -> None:
        self._enqueue(lambda: self._rpc("nvim_exec_lua", ["return ToadEditor.load(...)", [text]]))

    def edit(self, editor: TextArea, edit: Edit) -> None:
        async def replace() -> object:
            top_row, top_byte = self._byte_cursor(edit.top)
            bottom_row, bottom_byte = self._byte_cursor(edit.bottom)
            return await self._rpc("nvim_exec_lua", ["return ToadEditor.replace(...)",
                [top_row - 1, top_byte, bottom_row - 1, bottom_byte,
                 edit.text.split("\n"), edit.maintain_selection_offset]])
        self._enqueue(replace)

    def paste(self, editor: TextArea, text: str) -> None:
        self._enqueue(lambda: self._rpc("nvim_paste", [text, True, -1]))

    def undo(self, editor: TextArea) -> None:
        self._enqueue(lambda: self._rpc("nvim_command", ["undo"]))

    def redo(self, editor: TextArea) -> None:
        self._enqueue(lambda: self._rpc("nvim_command", ["redo"]))

    def selection_changed(self, editor: TextArea, selection: Selection) -> None:
        if selection.end != self.snapshot.state.cursor:
            self._enqueue(lambda: self._rpc("nvim_win_set_cursor", [0, self._byte_cursor(selection.end)]))

    def selection_range(self, editor: TextArea) -> Selection:
        return self.snapshot.state.selection(self.snapshot.lines)

    def selection_for_line(self, editor: TextArea, row: int) -> Selection:
        return self.snapshot.state.selection_for_line(self.snapshot.lines, row)
