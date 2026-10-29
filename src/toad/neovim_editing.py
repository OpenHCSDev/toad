"""Real modal editing. Neovim owns the buffer, registers, undo and input grammar."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from functools import cached_property
from importlib.resources import files
from itertools import count
from typing import ClassVar, Self

import msgpack
import toad
from agent_comms.child_process import AttachedChild, join_retirement
from agent_comms.declared_family import DeclaredFamily, UnknownFamilyMember
from agent_comms.field_codec import FieldCodec, MalformedRecord, NullMember, SingleFieldValue, SubclassUnion, boundary_decoder
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import log
from textual.binding import Binding
from textual.cursor_shape import BlinkingBar, CursorShape, SteadyBlock
from textual.document._document import DocumentBase, Location, RangedEditResult, Selection
from textual.document._editing import EditingFailure, EditingMode, VimMode
from textual.document._edit import Edit, InsertionPoint
from textual.events import Key
from textual.keys import key_to_character
from textual.message import Message
from textual.widgets import TextArea


class NeovimKey(DeclaredFamily, affix="Key"):
    """Only vocabulary differences are declared; native Neovim key names pass through."""

    notation: ClassVar[str]

    @classmethod
    def spelling(cls, name: str) -> str:
        try:
            return cls.member_named(name).notation
        except UnknownFamilyMember:
            return name


class EnterKey(NeovimKey):
    notation = "CR"


class EscapeKey(NeovimKey):
    notation = "Esc"


class BackspaceKey(NeovimKey):
    notation = "BS"


class DeleteKey(NeovimKey):
    notation = "Del"


class CtrlKey(NeovimKey):
    notation = "C"


class ShiftKey(NeovimKey):
    notation = "S"


class AltKey(NeovimKey):
    notation = "A"


class MetaKey(NeovimKey):
    notation = "M"


class SuperKey(NeovimKey):
    notation = "D"


class NeovimWireFailure(EditingFailure):
    """A child, transport or external Neovim protocol failure, not a Vim prefix."""


@dataclass(frozen=True)
class NeovimApiType:
    id: int
    prefix: str


@dataclass(frozen=True)
class NeovimApiMetadata:
    types: dict[str, NeovimApiType]

    @classmethod
    @boundary_decoder
    def from_response(cls, metadata: object) -> Self:
        if not isinstance(metadata, dict):
            raise NeovimWireFailure("Invalid Neovim API metadata")
        # Decode the declared field through its existing binding. Unused native
        # metadata stays opaque; no second record decoder or copied field key.
        binding, = FieldCodec.argument_fields(cls)
        return FieldCodec.construct(cls, binding.decoded_bound(metadata, {}))


@dataclass(frozen=True)
class NeovimApiInfo:
    channel: int
    metadata: NeovimApiMetadata

    @classmethod
    @boundary_decoder
    def from_response(cls, response: object) -> Self:
        if not isinstance(response, list) or len(response) != 2:
            raise NeovimWireFailure("Invalid Neovim API information response")
        channel, metadata = response
        return cls(FieldCodec.decode(int, channel), NeovimApiMetadata.from_response(metadata))


@dataclass(frozen=True)
class NeovimHandle(DeclaredFamily, affix="Handle"):
    """Native extension identity; its code belongs to this child's API metadata."""

    value: int

    @classmethod
    def api_name(cls) -> str:
        return cls.declared_name.capitalize()

    def extension(self, types: Mapping[str, NeovimApiType]) -> msgpack.ExtType:
        return msgpack.ExtType(types[self.api_name()].id, msgpack.packb(self.value))


class BufferHandle(NeovimHandle):
    pass


class WindowHandle(NeovimHandle):
    pass


class TabpageHandle(NeovimHandle):
    pass


@dataclass(frozen=True)
class NeovimMode:
    """The actual nvim_get_mode answer, decoded once inside a display update."""

    mode: str
    blocking: bool


@dataclass(frozen=True)
class NeovimRegion:
    start: Location
    end: Location

    def selection(self) -> Selection:
        return Selection(self.start, self.end)


@dataclass(frozen=True)
class NeovimDisplay:
    mode: NeovimMode
    cursor: Location
    command_line: str
    regions: tuple[NeovimRegion, ...]
    selected: str
    completed: int

    def state(self) -> NeovimState:
        member = next((member for member in NeovimState.members_with(NeovimState)
                       if member.recognizes(self.mode.mode)), NeovimState)
        return member(self.mode.blocking, self.cursor, self.command_line,
                      tuple(region.selection() for region in self.regions), self.selected)


@dataclass(frozen=True)
class NeovimState(DeclaredFamily, affix="State"):
    """Behaviour derives from a mode declaration, never from the last input key."""

    blocking: bool = True
    cursor: Location = (0, 0)
    command_line: str = ""
    regions: tuple[Selection, ...] = ()
    region_text: str = ""
    mode_codes: ClassVar[tuple[str, ...]] = ()
    mode_prefixes: ClassVar[tuple[str, ...]] = ()
    mode_name: ClassVar[str] = "NEOVIM"
    cursor_shape: ClassVar[CursorShape] = SteadyBlock()

    @classmethod
    def recognizes(cls, code: str) -> bool:
        return code in cls.mode_codes or any(code.startswith(prefix) for prefix in cls.mode_prefixes)

    @property
    def label(self) -> str:
        return self.mode_name + (" (PENDING)" if self.blocking else "")

    @property
    def accepts_text(self) -> bool:
        return False

    @property
    def allows_application_commands(self) -> bool:
        return False

    @property
    def allows_history_navigation(self) -> bool:
        return False

    @property
    def transferable(self) -> bool:
        return False

    def update(self, display: NeovimDisplay) -> NeovimState:
        return display.state()

    def completion(self, completion: NeovimCompletion) -> NeovimCompletion:
        return completion

    def fail(self, error: EditingFailure) -> NeovimState:
        return FailedState(cursor=self.cursor, command_line=self.command_line,
                           regions=self.regions, region_text=self.region_text, error=error)

    @property
    def binding_answers(self) -> tuple[bool, bool, bool]:
        return self.accepts_text, self.allows_application_commands, self.allows_history_navigation

    def raise_failure(self) -> None:
        pass

    def close_error(self) -> EditingFailure:
        return EditingFailure("Neovim editor closed; input was not replayed")

    def selection(self) -> Selection:
        return Selection.cursor(self.cursor)

    def selection_for_line(self, row: int) -> Selection:
        return self.selection()

    def selected_text(self) -> str:
        return ""


class TransferableState(NeovimState, declared_name=None):
    @property
    def transferable(self) -> bool:
        return not self.blocking


class TextEntryState(TransferableState, declared_name=None):
    cursor_shape = BlinkingBar()

    @property
    def accepts_text(self) -> bool:
        return not self.blocking


class HistoryState(NeovimState, declared_name=None):
    @property
    def allows_history_navigation(self) -> bool:
        return not self.blocking


class ApplicationCommandState(TransferableState, declared_name=None):
    @property
    def allows_application_commands(self) -> bool:
        return not self.blocking


class StartingState(NeovimState):
    mode_name = "NEOVIM STARTING"

    def snapshot(self) -> NeovimSnapshot:
        return NeovimSnapshot(self, NotCompleted())

    @property
    def label(self) -> str:
        return self.mode_name


@dataclass(frozen=True)
class FailedState(NeovimState):
    error: EditingFailure = field(kw_only=True)

    def update(self, display: NeovimDisplay) -> NeovimState:
        return self

    def completion(self, completion: NeovimCompletion) -> NeovimCompletion:
        return NotCompleted()

    def fail(self, error: EditingFailure) -> NeovimState:
        return self

    @property
    def label(self) -> str:
        return f"NEOVIM FAILED — {self.error} — draft preserved"

    def raise_failure(self) -> None:
        raise self.error

    def close_error(self) -> EditingFailure:
        return self.error


class InsertState(TextEntryState, HistoryState):
    mode_prefixes = ("i",)
    mode_name = "INSERT"


class NormalState(ApplicationCommandState, HistoryState):
    mode_codes = ("n",)
    mode_name = "NORMAL"


class ReplaceState(TextEntryState):
    mode_prefixes = ("R",)
    mode_name = "REPLACE"


class OperatorState(NeovimState):
    mode_prefixes = ("no",)
    mode_name = "OPERATOR"


class CommandLineState(NeovimState):
    mode_codes = ("c",)
    mode_name = "COMMAND"


class VisualState(TransferableState):
    mode_codes = ("v", "s")
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
    mode_codes = ("V", "S")
    mode_name = "VISUAL LINE"


class BlockVisualState(VisualState):
    mode_codes = ("\x16", "\x13")
    mode_name = "VISUAL BLOCK"


class DetachedReceiver:
    """An engine may outlive its widget; detachment is not child failure."""

    def attach(self, editor: TextArea) -> AttachedReceiver:
        self.prepare_editor(editor)
        return AttachedReceiver(editor)

    def prepare_editor(self, editor: TextArea) -> None:
        pass

    def require(self) -> TextArea:
        raise EditingFailure("Neovim requires an attached editor")

    def owns(self, editor: TextArea) -> bool:
        return False

    def visit(self, action: Callable[[TextArea], object]) -> None:
        pass

    def boundary(self, binding: Binding) -> bool:
        return False

    def project(self, changes: Sequence[NeovimChange]) -> None:
        pass

    def finish_projection(self) -> None:
        pass


class RetainedReceiver(DetachedReceiver):
    """A captured document remains the projection without retaining its widget."""

    def __init__(self, document: DocumentBase) -> None:
        self._document = document

    @property
    def document(self) -> DocumentBase:
        return self._document

    def prepare_editor(self, editor: TextArea) -> None:
        if editor.document is not self.document:
            editor.set_document(self.document)

    def project(self, changes: Sequence[NeovimChange]) -> None:
        for change in changes:
            self.project_edit(change.apply(self.document))

    def project_edit(self, result: RangedEditResult) -> None:
        pass


class AttachedReceiver(RetainedReceiver):
    def __init__(self, editor: TextArea) -> None:
        self._editor = editor

    @property
    def document(self) -> DocumentBase:
        return self._editor.document

    def project_edit(self, result: RangedEditResult) -> None:
        self._editor.project_engine_edit(result)

    def finish_projection(self) -> None:
        self._editor.finish_engine_changes()

    def require(self) -> TextArea:
        return self._editor

    def owns(self, editor: TextArea) -> bool:
        return self._editor is editor

    def visit(self, action: Callable[[TextArea], object]) -> None:
        if self._editor.is_attached:
            action(self._editor)

    def boundary(self, binding: Binding) -> bool:
        return self._editor.is_attached and binding.engine_boundary(self._editor)


class NeovimRequest(ABC):
    """One queued request; the writer never waits for its eventual reply."""

    _identities = count(1)

    def __init__(self) -> None:
        self.identity = next(self._identities)
        self.reply: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self.dispatched: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    @property
    @abstractmethod
    def method(self) -> str: ...

    @property
    @abstractmethod
    def arguments(self) -> Sequence[object]: ...

    async def send(self, owner: NeovimEditing) -> None:
        self.dispatched.set_result(None)
        await owner.write_frame([0, self.identity, self.method, list(self.arguments)])

    def resolve(self, value: object) -> None:
        self.reply.set_result(value)

    async def result(self) -> object:
        await asyncio.shield(self.dispatched)
        return await self.wait_reply()

    async def wait_reply(self) -> object:
        return await asyncio.shield(self.reply)


class NeovimFastRequest(NeovimRequest):
    async def wait_reply(self) -> object:
        try:
            async with asyncio.timeout(5):
                return await super().wait_reply()
        except TimeoutError as error:
            raise NeovimWireFailure(f"Neovim fast request {self.method} did not reply") from error


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


class NeovimOperation(NeovimCall):
    """Programmatic mutation executes on the same engine and invalidates its proof."""

    operation: ClassVar[str] = "assert(vim.api[operation], operation)"

    def __init__(self, generation: int, method: str, arguments: Sequence[object]) -> None:
        super().__init__("nvim_exec_lua", [
            "local serial, operation, arguments = ...; "
            f"return ToadEditor.call(serial, {self.operation}, arguments)",
            [generation, method, list(arguments)],
        ])


class NeovimLuaOperation(NeovimOperation):
    """Lua chunks are not API names: nvim_exec_lua itself is RPC-only."""

    operation = "assert(loadstring(operation))"


class NeovimInput(NeovimFastRequest):
    method = "nvim__exec_lua_fast"

    def __init__(self, generation: int, keys: str) -> None:
        super().__init__()
        self.generation, self.keys = generation, keys

    @property
    def arguments(self) -> Sequence[object]:
        return ("return ToadEditor.input(...)", [self.generation, self.keys])

    def resolve(self, value: object) -> None:
        accepted = FieldCodec.decode(int, value)
        if accepted != len(self.keys.encode("utf-8")):
            raise NeovimWireFailure("Neovim did not accept the complete key; it was not replayed")
        super().resolve(accepted)


class NeovimChange(ABC):
    @abstractmethod
    def apply(self, document: DocumentBase) -> RangedEditResult: ...


@dataclass(frozen=True)
class NeovimLineChange(NeovimChange):
    first: int
    last: int
    lines: tuple[str, ...]

    def apply(self, document: DocumentBase) -> RangedEditResult:
        return document.replace_lines(self.first, self.last, self.lines)


@dataclass(frozen=True)
class NeovimBufferTransfer(NeovimChange):
    lines: tuple[str, ...]

    def apply(self, document: DocumentBase) -> RangedEditResult:
        return document.replace_lines(0, document.line_count, self.lines)


class NeovimCompletion(ABC):
    @classmethod
    @boundary_decoder
    def from_native(cls, generation: int) -> NeovimCompletion:
        if generation == -1:
            return NotCompleted()
        if generation < 0:
            raise NeovimWireFailure("Invalid Neovim completed generation")
        return CompletedGeneration(generation)

    @abstractmethod
    def matches(self, generation: int) -> bool: ...


@dataclass(frozen=True)
class NotCompleted(NeovimCompletion):
    def matches(self, generation: int) -> bool:
        return False


@dataclass(frozen=True)
class CompletedGeneration(NeovimCompletion):
    generation: int

    def matches(self, generation: int) -> bool:
        return self.generation == generation


@dataclass(frozen=True)
class NeovimSnapshot:
    state: NeovimState
    completed: NeovimCompletion

    def with_lines(self) -> NeovimSnapshot:
        return NeovimSnapshot(self.state, self.completed)

    def with_display(self, display: NeovimDisplay) -> NeovimSnapshot:
        state = self.state.update(display)
        return NeovimSnapshot(state, state.completion(NeovimCompletion.from_native(display.completed)))

    def with_boundary(self, display: NeovimDisplay) -> NeovimSnapshot:
        # A mapping's in-command display is not a SafeState certificate.
        return NeovimSnapshot(self.state.update(display), NotCompleted())

    def with_failure(self, error: EditingFailure) -> NeovimSnapshot:
        return NeovimSnapshot(self.state.fail(error), NotCompleted())

    def unpainted(self) -> UnpaintedSnapshot:
        return UnpaintedSnapshot(self.state, self.completed)

    def matches[Answer](self, current: NeovimState,
                        answer: Callable[[NeovimState], Answer]) -> bool:
        return answer(self.state) == answer(current)


class UnpaintedSnapshot(NeovimSnapshot):
    """A new view has presented none of the retained owner's answers yet."""

    def matches[Answer](self, current: NeovimState,
                        answer: Callable[[NeovimState], Answer]) -> bool:
        return False


class NeovimUpdated(Message):
    def __init__(self, owner: NeovimEditing) -> None:
        super().__init__()
        self.owner = owner


class NeovimMethod:
    method: ClassVar[str]

    @classmethod
    def selection_key(cls) -> str:
        return cls.method


class NeovimNotification(NeovimMethod, DeclaredFamily, affix="Notification"):
    @classmethod
    @abstractmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> None: ...


class DisplayNotification(NeovimNotification):
    method = "toad_editor_state"

    @classmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> None:
        display, = FieldCodec.decode(tuple[NeovimDisplay], arguments)
        owner.accept_display(display)


class LinesNotification(NeovimNotification):
    method = "toad_editor_lines"

    @classmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> None:
        change, = FieldCodec.decode(tuple[NeovimLineChange], arguments)
        owner.accept_lines(change)


class RedrawNotification(NeovimNotification):
    """The attached UI drives Neovim, but TextArea paints buffer projections."""

    method = "redraw"

    @classmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> None:
        pass


class NeovimHostRequest(NeovimMethod, DeclaredFamily, affix="Request"):
    @classmethod
    @abstractmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> object: ...


class CursorBoundaryRequest(NeovimHostRequest):
    method = "toad_cursor_boundary"

    @classmethod
    def receive(cls, owner: NeovimEditing, arguments: object) -> bool:
        boundary, display = FieldCodec.decode(tuple[int, NeovimDisplay], arguments)
        return owner.engine_boundary(boundary, display)


class NeovimReply(SubclassUnion, affix="Reply"):
    @abstractmethod
    def resolve(self, request: NeovimRequest, value: object) -> None: ...


class SuccessfulReply(NullMember, NeovimReply):
    def resolve(self, request: NeovimRequest, value: object) -> None:
        request.resolve(value)


@dataclass(frozen=True)
class ErrorReply(SingleFieldValue, NeovimReply):
    details: tuple[int, str]

    def resolve(self, request: NeovimRequest, value: object) -> None:
        code, message = self.details
        request.reply.set_exception(NeovimWireFailure(f"Neovim {request.method} ({code}): {message}"))


class NeovimFrame(DeclaredFamily, affix="Frame"):
    kind: ClassVar[int]

    @classmethod
    def selection_key(cls) -> int:
        return cls.kind

    @abstractmethod
    def __init__(self, *payload: object) -> None:
        if payload:
            raise NeovimWireFailure("Unexpected Neovim RPC header fields")

    @classmethod
    @boundary_decoder
    def from_payload(cls, payload: Sequence[object]) -> Self:
        try:
            return cls(*payload)
        except TypeError as error:
            raise NeovimWireFailure(f"Invalid {cls.__name__} header or arity") from error

    @abstractmethod
    async def receive(self, owner: NeovimEditing) -> None: ...


class IdentifiedFrame(NeovimFrame, declared_name=None):
    def __init__(self, identity: object, *payload: object) -> None:
        self.identity = FieldCodec.decode(int, identity)
        super().__init__(*payload)


class MethodFrame(NeovimFrame, declared_name=None):
    def __init__(self, method: object, arguments: object) -> None:
        self.method = FieldCodec.decode(str, method)
        self.arguments = arguments
        super().__init__()


class ResponseFrame(IdentifiedFrame):
    kind = 1

    def __init__(self, identity: object, reply: object, value: object) -> None:
        super().__init__(identity)
        self.reply = FieldCodec.decode(NeovimReply, reply)
        self.value = value

    async def receive(self, owner: NeovimEditing) -> None:
        owner.resolve_reply(self.identity, self.reply, self.value)


class NotificationFrame(MethodFrame):
    kind = 2

    async def receive(self, owner: NeovimEditing) -> None:
        NeovimNotification.member_selected(self.method).receive(owner, self.arguments)


class RequestFrame(IdentifiedFrame, MethodFrame):
    kind = 0

    async def receive(self, owner: NeovimEditing) -> None:
        reply = NeovimHostRequest.member_selected(self.method).receive(owner, self.arguments)
        await owner.answer_request(self.identity, reply)


class NeovimEditing(VimMode, MroDispatch):
    """One engine, one input queue, completed snapshots only from SafeState."""

    initial_keys = ""

    def __init__(self) -> None:
        self._receiver: DetachedReceiver = DetachedReceiver()
        self._pending: dict[int, NeovimRequest] = {}
        self._outgoing: asyncio.Queue[NeovimRequest] = asyncio.Queue()
        self._generation = 0
        self.snapshot = StartingState().snapshot()
        self._changes: list[NeovimChange] = []
        self._rendered: NeovimSnapshot = self.snapshot.unpainted()
        self._update_queued = False
        self._boundaries: list[Binding] = []
        self._api_types: dict[str, NeovimApiType] = {}

    @property
    def label(self) -> str:
        state = self.snapshot.state
        return f"{state.label} {state.command_line}".rstrip()

    @property
    def completed(self) -> bool:
        return (self.snapshot.completed.matches(self._generation)
                and not self._pending and not self._changes)

    @property
    def accepts_text(self) -> bool:
        return self.completed and self.snapshot.state.accepts_text

    @property
    def allows_application_commands(self) -> bool:
        return self.completed and self.snapshot.state.allows_application_commands

    @property
    def allows_history_navigation(self) -> bool:
        # The engine's expression mapping calls this boundary while an arrow is
        # executing. That input cannot already have a SafeState completion.
        return self.snapshot.state.allows_history_navigation

    @property
    def cursor_shape(self) -> CursorShape:
        return self.snapshot.state.cursor_shape

    @property
    def binding_mode(self) -> type[EditingMode]:
        return type(self)

    @cached_property
    def _started(self) -> asyncio.Task[None]:
        editor = self._receiver.require()
        self._initial_lines = tuple(editor.document.lines)
        self._initial_selection = editor.selection
        self._child_ready: asyncio.Future[AttachedChild] = asyncio.get_running_loop().create_future()
        self._lifetime = editor.app.run_worker(self._run(), name="Neovim editor", exit_on_error=True)
        task = asyncio.create_task(self._start())
        task.add_done_callback(self._observe_failure)
        return task

    def attach(self, editor: TextArea) -> None:
        changed_receiver = not self._receiver.owns(editor)
        self._receiver = self._receiver.attach(editor)
        if changed_receiver:
            self._update_queued = False
            editor.history.clear()
        # Even the same receiver may have rebuilt its width-dependent view.
        self._rendered = self._rendered.unpainted()
        started = self._started
        if started.done() and not started.cancelled():
            self.paint(editor)

    def resume(self, editor: TextArea) -> None:
        pass

    def suspend(self, editor: TextArea) -> None:
        pass

    def capture(self, editor: TextArea) -> NeovimEditing:
        self._receiver = RetainedReceiver(editor.document)
        return self

    async def unmount(self, editor: TextArea) -> None:
        if self._receiver.owns(editor):
            await self.close()

    async def close(self) -> None:
        started = self._started
        self._receiver = DetachedReceiver()
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
                    tasks.create_task(self._write_queued())
                    await self._read(child)
        except* (EditingFailure, OSError, msgpack.UnpackException,
                 UnicodeDecodeError, MalformedRecord) as errors:
            self._fail(NeovimWireFailure("; ".join(str(error) for error in errors.exceptions)))
        finally:
            error = self.snapshot.state.close_error()
            if not self._child_ready.done():
                self._child_ready.set_exception(error)
            for request in self._pending.values():
                if not request.dispatched.done():
                    request.dispatched.set_exception(error)
                if not request.reply.done():
                    request.reply.set_exception(error)
            self._pending.clear()

    @cached_property
    def _unpacker(self) -> msgpack.Unpacker:
        return msgpack.Unpacker(raw=False, strict_map_key=False,
                                max_buffer_size=16 * 1024 * 1024,
                                ext_hook=self._decode_handle)

    @boundary_decoder
    async def _read(self, child: AttachedChild) -> None:
        stream = child.stdout
        assert stream is not None
        while chunk := await stream.read(65536):
            self._unpacker.feed(chunk)
            for message in self._unpacker:
                await self._receive(message)
        raise NeovimWireFailure(f"Neovim exited: {await child.stderr_tail()}")

    def accept_api_info(self, response: object) -> NeovimApiInfo:
        api = NeovimApiInfo.from_response(response)
        self._api_types = api.metadata.types
        return api

    @boundary_decoder
    def _decode_handle(self, code: int, data: bytes) -> NeovimHandle:
        try:
            name = next(name for name, definition in self._api_types.items()
                        if definition.id == code)
            member = NeovimHandle.member_named(name.casefold())
        except (StopIteration, UnknownFamilyMember) as error:
            raise NeovimWireFailure(f"Unknown Neovim extension code {code}") from error
        return member(FieldCodec.decode(int, msgpack.unpackb(data, raw=False)))

    @boundary_decoder
    def _encode_handle(self, value: object) -> msgpack.ExtType:
        try:
            encoder: Callable[[NeovimEditing, object], msgpack.ExtType] = self.handler_for(type(value))
        except StopIteration as error:
            raise NeovimWireFailure("Unsupported Neovim MessagePack value") from error
        return encoder(self, value)

    @handles(NeovimHandle)
    def _native_handle(self, value: NeovimHandle) -> msgpack.ExtType:
        try:
            return value.extension(self._api_types)
        except KeyError as error:
            raise NeovimWireFailure("Unknown Neovim extension type") from error

    async def write_frame(self, frame: Sequence[object]) -> None:
        try:
            await self._child.write(msgpack.packb(
                frame, use_bin_type=True, default=self._encode_handle))
        except OSError as error:
            raise NeovimWireFailure(str(error)) from error

    async def _write_queued(self) -> None:
        await self._started
        while True:
            request = await self._outgoing.get()
            await request.send(self)

    def _register(self, request: NeovimRequest) -> None:
        request.reply.add_done_callback(self._observe_failure)
        request.dispatched.add_done_callback(self._observe_failure)
        self.snapshot.state.raise_failure()
        self._pending[request.identity] = request

    async def _bootstrap(self, request: NeovimRequest) -> object:
        self._register(request)
        await request.send(self)
        return await request.result()

    def _enqueue(self, request: NeovimRequest) -> asyncio.Task[object]:
        try:
            self._register(request)
        except EditingFailure as error:
            request.dispatched.set_exception(error)
            request.reply.set_exception(error)
        else:
            self._outgoing.put_nowait(request)
        result = asyncio.create_task(request.result())
        result.add_done_callback(self._observe_failure)
        return result

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation

    def _call(self, method: str, arguments: Sequence[object]) -> asyncio.Future[object]:
        return self._enqueue(NeovimOperation(self._next_generation(), method, arguments))

    def _lua(self, code: str, arguments: Sequence[object]) -> asyncio.Future[object]:
        return self._enqueue(NeovimLuaOperation(self._next_generation(), code, arguments))

    def _input(self, keys: str) -> asyncio.Future[object]:
        return self._enqueue(NeovimInput(self._next_generation(), keys))

    async def _start(self) -> None:
        await self._child_ready
        editor = self._receiver.require()
        width, height = max(1, editor.wrap_width), max(3, editor.content_size.height + 2)
        api = self.accept_api_info(await self._bootstrap(NeovimCall("nvim_get_api_info", [])))
        await self._bootstrap(NeovimCall("nvim_ui_attach", [width, height,
            {"ext_linegrid": True, "ext_cmdline": True, "ext_messages": True}]))
        initial_lines = self._initial_lines
        undo_levels = await self._bootstrap(NeovimCall("nvim_get_option_value", ["undolevels", {"buf": 0}]))
        await self._bootstrap(NeovimCall("nvim_set_option_value", ["undolevels", -1, {"buf": 0}]))
        await self._bootstrap(NeovimCall("nvim_buf_set_lines", [0, 0, -1, True, list(initial_lines)]))
        await self._bootstrap(NeovimCall("nvim_set_option_value", ["undolevels", undo_levels, {"buf": 0}]))
        initial_cursor = self._initial_selection.end
        row, column = initial_cursor
        await self._bootstrap(NeovimCall("nvim_win_set_cursor", [0,
            [row + 1, len(initial_lines[row][:column].encode("utf-8"))]]))
        script = files(toad).joinpath("neovim_editing.lua").read_text()
        mappings: list[list[object]] = []
        for key, binding in editor.binding_map(type(self)):
            for spelling, native in binding.declared_key.input_bindings(key):
                index = len(self._boundaries)
                self._boundaries.append(binding)
                mappings.append([self.input_code(spelling), self.input_code(native), index])
        await self._bootstrap(NeovimCall("nvim_exec_lua", [script, [mappings, api.channel]]))
        await self._bootstrap(NeovimCall("nvim_set_option_value", ["tabstop", editor.indent_width, {}]))
        if self.initial_keys:
            await self._bootstrap(NeovimInput(self._next_generation(), self.initial_keys))
            await self._bootstrap(NeovimLuaOperation(self._next_generation(),
                                                   "return ToadEditor.cursor(...)", [initial_cursor]))

    @boundary_decoder
    async def _receive(self, message: object) -> None:
        """Decode the envelope tag here; its member alone decodes the raw payload."""
        if not isinstance(message, list) or not message:
            raise NeovimWireFailure("Invalid Neovim RPC message")
        kind = FieldCodec.decode(int, message[0])
        try:
            frame = NeovimFrame.member_selected(kind).from_payload(message[1:])
            await frame.receive(self)
        except UnknownFamilyMember as error:
            raise NeovimWireFailure(str(error)) from error

    def resolve_reply(self, identity: int, reply: NeovimReply, value: object) -> None:
        try:
            request = self._pending[identity]
        except KeyError as error:
            raise NeovimWireFailure("Unexpected Neovim RPC response") from error
        reply.resolve(request, value)
        del self._pending[identity]
        # SafeState can arrive before the final RPC admission response. Its
        # publication and that response must invalidate the same view owner.
        if self.completed:
            self.request_paint()

    def engine_boundary(self, boundary: int, display: NeovimDisplay) -> bool:
        if not 0 <= boundary < len(self._boundaries):
            raise NeovimWireFailure("Unknown Neovim cursor boundary")
        self.publish(self.snapshot.with_boundary(display))
        self._receiver.visit(self.render)
        return self._receiver.boundary(self._boundaries[boundary])

    async def answer_request(self, identity: int, reply: object) -> None:
        await self.write_frame([1, identity, None, reply])

    def accept_lines(self, change: NeovimLineChange) -> None:
        if change.last == -1:
            self._changes.append(NeovimBufferTransfer(change.lines))
        else:
            self._changes.append(change)
        self.snapshot = self.snapshot.with_lines()

    def accept_display(self, display: NeovimDisplay) -> None:
        self.publish(self.snapshot.with_display(display))

    def publish(self, snapshot: NeovimSnapshot) -> None:
        """Project preceding lines before exposing the display that describes them."""
        changes, self._changes = self._changes, []
        if changes:
            self._receiver.project(changes)
        self.snapshot = snapshot
        if changes:
            self._receiver.finish_projection()
        self.request_paint()

    def request_paint(self) -> None:
        """One coalesced paint slot for display and RPC completion changes."""
        if not self._update_queued:
            def post(editor: TextArea) -> None:
                self._update_queued = editor.post_message(NeovimUpdated(self))
            self._receiver.visit(post)

    def paint(self, editor: TextArea) -> None:
        if not self._receiver.owns(editor):
            return
        self._update_queued = False
        # A later line batch may precede its display while a message waits.
        if not self._changes:
            self.render(editor)

    def render(self, editor: TextArea) -> None:
        if editor.editing_mode is not self or not self._receiver.owns(editor):
            return
        if self._changes:
            raise RuntimeError("Cannot paint an unpublished Neovim line batch")
        if self.snapshot is self._rendered:
            return
        previous, current = self._rendered, self.snapshot.state
        if not previous.matches(current, lambda state: state.cursor):
            editor.paint_selection(Selection.cursor(current.cursor))
            editor.record_cursor_width()
        if not previous.matches(current, lambda state: state.regions):
            editor.invalidate_engine_regions((*previous.state.regions, *current.regions))
        if not previous.matches(current, lambda state: (state.label, state.command_line)):
            editor.show_editing_mode(self)
        if not previous.matches(current, lambda state: state.binding_answers):
            editor.refresh_bindings()
        self._rendered = self.snapshot

    def _observe_failure[Result](self, result: asyncio.Future[Result]) -> None:
        try:
            result.result()
        except asyncio.CancelledError:
            pass
        except EditingFailure as error:
            self._fail(error)

    def _fail(self, error: EditingFailure) -> None:
        failed = self.snapshot.with_failure(error)
        if failed.state is self.snapshot.state:
            return
        log.error("Neovim editing failed:", error)
        self.publish(failed)
        def notify(editor: TextArea) -> None:
            editor.notify(f"{error}. The displayed draft is preserved. Input was not replayed.",
                          title="Neovim editing failed", severity="error", timeout=0)
        self._receiver.visit(notify)

    async def finish(self, editor: TextArea) -> bool:
        return await self.flush(editor)

    async def flush(self, editor: TextArea) -> bool:
        """Never wait for deferred RPC in App dispatch. Missing completion refuses."""
        self.snapshot.state.raise_failure()
        if not self.completed:
            return False
        self.render(editor)
        return self.snapshot.state.transferable

    async def prepare_input(self, editor: TextArea) -> bool:
        # Only fence the widget queue, never the Neovim event loop. Escape must
        # remain admissible while a deferred operation is waiting for an operand.
        finished: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        def ready() -> None:
            finished.set_result(True)
        if not editor.call_later(ready):
            return False
        return await finished

    async def handle_key(self, editor: TextArea, event: Key) -> bool:
        try:
            await self._input(self.input_code(event.key, event.character or ""))
        except EditingFailure:
            pass  # The child/wire failure was reported; never replay input.
        return True

    @staticmethod
    def input_code(key: str, character: str = "") -> str:
        """Textual's foreign key vocabulary enters Neovim at this boundary."""
        *modifiers, name = key.split("+")
        literal = character or key_to_character(name) or ""
        is_character = bool(literal) and literal.isprintable()
        if not modifiers and is_character:
            return literal.replace("<", "<LT>")
        base = literal if is_character else NeovimKey.spelling(name)
        base = base.replace("<", "LT")
        return "<" + "-".join([*(NeovimKey.member_named(part).notation for part in modifiers), base]) + ">"

    def resize(self, editor: TextArea) -> None:
        # This UI API is RPC-only, like nvim_ui_attach during startup. A
        # viewport resize is not a buffer edit and must not advance its generation.
        self._enqueue(NeovimCall("nvim_ui_try_resize",
                                [max(1, editor.wrap_width), max(3, editor.content_size.height + 2)]))

    def enter_text(self, editor: TextArea) -> None:
        self._input("<Esc>i")

    def load_text(self, editor: TextArea, text: str) -> None:
        self._lua("return ToadEditor.load(...)", [text])

    def edit(self, editor: TextArea, edit: Edit) -> None:
        self._lua("return ToadEditor.replace(...)",
            [edit.top, edit.bottom, edit.text.split("\n"), edit.maintain_selection_offset])

    def insert(self, editor: TextArea, text: str, point: InsertionPoint, maintain_selection_offset: bool) -> None:
        self._lua("return ToadEditor.insert(...)",
            [text.split("\n"), point.engine_location(), maintain_selection_offset])

    def clear(self, editor: TextArea) -> None:
        self.load_text(editor, "")

    def move_to_end(self, editor: TextArea) -> None:
        self._lua("return ToadEditor.cursor_end()", [])

    def paste(self, editor: TextArea, text: str) -> None:
        self._call("nvim_paste", [text, True, -1])

    def undo(self, editor: TextArea) -> None:
        self._call("nvim_command", ["undo"])

    def redo(self, editor: TextArea) -> None:
        self._call("nvim_command", ["redo"])

    def request_selection(self, editor: TextArea, selection: Selection) -> Selection:
        if not selection.is_empty:
            self._input("<Esc>")
            self._lua("return ToadEditor.select(...)", sorted(selection))
        elif selection.end != self.snapshot.state.cursor:
            self._lua("return ToadEditor.cursor(...)", [selection.end])
        return editor.selection

    def selection_range(self, editor: TextArea) -> Selection:
        return self.snapshot.state.selection()

    def selection_for_line(self, editor: TextArea, row: int) -> Selection:
        return self.snapshot.state.selection_for_line(row)

    def selected_text(self, editor: TextArea) -> str:
        return self.snapshot.state.selected_text()
