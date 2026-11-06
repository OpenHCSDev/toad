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
from agent_comms.nominal.declared_family import DeclaredFamily, UnknownFamilyMember
from agent_comms.nominal.field_codec import FieldCodec, MalformedRecord, NullMember, SingleFieldValue, SubclassUnion, boundary_decoder
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import log
from textual.app import App
from textual.binding import Binding
from textual.cursor_shape import CursorShape, SteadyBlock, TextEntryCursor
from textual.document._document import DocumentBase, Location, RangedEditResult, Selection
from textual.document._editing import EditingFailure, EditingMode, VimMode
from textual.document._edit import Edit, InsertionPoint
from textual.events import Key
from textual.keys import key_to_character
from textual.message import Message
from textual.widgets import TextArea
from toad.neovim_runtime import Neovim


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
    cursor_shape = TextEntryCursor()

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

    def project(self, changes: Sequence[NeovimChange], cursor: Location) -> None:
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

    def project(self, changes: Sequence[NeovimChange], cursor: Location) -> None:
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

    def project(self, changes: Sequence[NeovimChange], cursor: Location) -> None:
        """Publish the document and its cursor before size-dependent effects."""
        super().project(changes, cursor)
        if self._editor.cursor_location != cursor:
            self._editor.paint_selection(Selection.cursor(cursor))
            self._editor.record_cursor_width()

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

    async def send(self, host: NeovimHost) -> None:
        self.dispatched.set_result(None)
        await host.write_frame([0, self.identity, self.method, list(self.arguments)])

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


class HoldsBuffer(ABC):
    """Whose buffer a request acts on. A key typed before the buffer is open is queued, so the
    request reads the number when it is sent, not when it is made."""

    @property
    @abstractmethod
    def buffer(self) -> int: ...


class NeovimOperation(NeovimCall):
    """Programmatic mutation executes on its session's buffer and invalidates that buffer's proof."""

    operation: ClassVar[str] = "assert(vim.api[operation], operation)"

    def __init__(self, holder: HoldsBuffer, generation: int, method: str, arguments: Sequence[object]) -> None:
        super().__init__("nvim_exec_lua", arguments)
        self.holder, self.generation, self.operation_name = holder, generation, method

    @property
    def arguments(self) -> Sequence[object]:
        return ["local buffer, serial, operation, arguments = ...; "
                f"return ToadEditor.call(buffer, serial, {self.operation}, arguments)",
                [self.holder.buffer, self.generation, self.operation_name, list(self._arguments)]]


class NeovimLuaOperation(NeovimOperation):
    """Lua chunks are not API names: nvim_exec_lua itself is RPC-only."""

    operation = "assert(loadstring(operation))"


class NeovimInput(NeovimFastRequest):
    method = "nvim__exec_lua_fast"

    def __init__(self, holder: HoldsBuffer, generation: int, keys: str) -> None:
        super().__init__()
        self.holder, self.generation, self.keys = holder, generation, keys

    @property
    def arguments(self) -> Sequence[object]:
        return ("return ToadEditor.input(...)", [self.holder.buffer, self.generation, self.keys])

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
    def receive(cls, host: NeovimHost, arguments: object) -> None: ...


class DisplayNotification(NeovimNotification):
    method = "toad_editor_state"

    @classmethod
    def receive(cls, host: NeovimHost, arguments: object) -> None:
        buffer, display = FieldCodec.decode(tuple[int, NeovimDisplay], arguments)
        host.session(buffer).accept_display(display)


class LinesNotification(NeovimNotification):
    method = "toad_editor_lines"

    @classmethod
    def receive(cls, host: NeovimHost, arguments: object) -> None:
        buffer, change = FieldCodec.decode(tuple[int, NeovimLineChange], arguments)
        host.session(buffer).accept_lines(change)


class RedrawNotification(NeovimNotification):
    """The attached UI drives Neovim, but TextArea paints buffer projections."""

    method = "redraw"

    @classmethod
    def receive(cls, host: NeovimHost, arguments: object) -> None:
        pass


class NeovimHostRequest(NeovimMethod, DeclaredFamily, affix="Request"):
    @classmethod
    @abstractmethod
    def receive(cls, host: NeovimHost, arguments: object) -> object: ...


class CursorBoundaryRequest(NeovimHostRequest):
    method = "toad_cursor_boundary"

    @classmethod
    def receive(cls, host: NeovimHost, arguments: object) -> bool:
        buffer, boundary, display = FieldCodec.decode(tuple[int, int, NeovimDisplay], arguments)
        return host.session(buffer).engine_boundary(boundary, display)


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
    async def receive(self, host: NeovimHost) -> None: ...


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

    async def receive(self, host: NeovimHost) -> None:
        host.resolve_route(self.identity, self.reply, self.value)


class NotificationFrame(MethodFrame):
    kind = 2

    async def receive(self, host: NeovimHost) -> None:
        NeovimNotification.member_selected(self.method).receive(host, self.arguments)


class RequestFrame(IdentifiedFrame, MethodFrame):
    kind = 0

    async def receive(self, host: NeovimHost) -> None:
        reply = NeovimHostRequest.member_selected(self.method).receive(host, self.arguments)
        await host.answer_request(self.identity, reply)


class NeovimRequester(ABC):
    """Whoever sent a request is the one its reply resolves: the host for the engine's own
    bootstrap, a session for its buffer, whose completion proof waits on its pending replies."""

    @abstractmethod
    def resolve_reply(self, request: NeovimRequest, reply: NeovimReply, value: object) -> None: ...


@dataclass(frozen=True)
class NeovimRoute:
    requester: NeovimRequester
    request: NeovimRequest

    def resolve(self, reply: NeovimReply, value: object) -> None:
        self.requester.resolve_reply(self.request, reply, value)


class EngineEnding(ABC):
    """How the engine's life ended decides what everything still waiting on it is told."""

    @abstractmethod
    def end(self, host: NeovimHost) -> None: ...


class EngineShutDown(EngineEnding):
    """The application closed it: what was still waiting is cancelled, never reported."""

    def end(self, host: NeovimHost) -> None:
        host.end_requests()
        host.end_start(lambda ready: ready.cancel())


@dataclass(frozen=True)
class EngineFailed(EngineEnding):
    """It died. Requests in flight are cancelled, never failed: their input is not replayed, and
    a failure arriving after the restart would fail the reopened buffer. Every open buffer
    reopens in a new engine and says why. A session still waiting for this engine to start
    fails with the reason, so an engine that cannot start is never restarted in a loop."""

    failure: EditingFailure

    def end(self, host: NeovimHost) -> None:
        host.end_requests()
        host.end_start(lambda ready: ready.set_exception(self.failure))
        host.restart_sessions(self.failure)


class NeovimSession(NeovimRequester):
    """What the host routes a buffer's notifications to."""

    @abstractmethod
    def accept_display(self, display: NeovimDisplay) -> None: ...

    @abstractmethod
    def accept_lines(self, change: NeovimLineChange) -> None: ...

    @abstractmethod
    def engine_boundary(self, boundary: int, display: NeovimDisplay) -> bool: ...

    @abstractmethod
    def engine_failed(self, error: EditingFailure) -> None: ...

    def resolve_reply(self, request: NeovimRequest, reply: NeovimReply, value: object) -> None:
        reply.resolve(request, value)


class UnclaimedBuffer(NeovimSession):
    """A buffer no editing session holds: the engine's first buffer, which also parks the
    window while a closed session's buffer is deleted. Its updates have no reader."""

    def accept_display(self, display: NeovimDisplay) -> None:
        pass

    def accept_lines(self, change: NeovimLineChange) -> None:
        pass

    def engine_boundary(self, boundary: int, display: NeovimDisplay) -> bool:
        return False

    def engine_failed(self, error: EditingFailure) -> None:
        pass


UNCLAIMED = UnclaimedBuffer()


class NeovimHost(NeovimRequester, MroDispatch):
    """The application's one embedded Neovim. Each editing session is a buffer in it, so the
    process count no longer grows with the tabs; registers and the search pattern are shared
    across those buffers on purpose, as in any one Neovim."""

    # The one UI's size until a prompt measures its own viewport.
    initial_viewport: ClassVar[tuple[int, int]] = (80, 24)

    def __init__(self, application: HostsNeovim) -> None:
        self._application = application
        self._routes: dict[int, NeovimRoute] = {}
        self._outgoing: asyncio.Queue[NeovimRequest] = asyncio.Queue()
        self._api_types: dict[str, NeovimApiType] = {}
        self._sessions: dict[int, NeovimSession] = {}
        self._focused: NeovimSession = UNCLAIMED

    @cached_property
    def ready(self) -> asyncio.Task[None]:
        self._child_ready: asyncio.Future[AttachedChild] = asyncio.get_running_loop().create_future()
        self._lifetime = self._application.run_worker(self._run(), name="Neovim", exit_on_error=True)
        return asyncio.create_task(self._start())

    def session(self, buffer: int) -> NeovimSession:
        return self._sessions.get(buffer, UNCLAIMED)

    async def _run(self) -> None:
        try:
            async with AsyncExitStack() as cleanup:
                async def acquire_child() -> AttachedChild:
                    child = await AttachedChild.start(Neovim().command())
                    cleanup.push_async_callback(child.stop)
                    return child

                spawn = asyncio.create_task(acquire_child())
                try:
                    child = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    await join_retirement(spawn)
                    raise
                self._child = child
                self._child_ready.set_result(child)
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(self._write_queued())
                    await self._read(child)
        except* (EditingFailure, OSError, msgpack.UnpackException,
                 UnicodeDecodeError, MalformedRecord) as errors:
            self._ending = EngineFailed(
                NeovimWireFailure("; ".join(str(error) for error in errors.exceptions)))
        finally:
            # Forgotten first, so a buffer reopening after a failure finds a new engine.
            self._application.forget_neovim()
            self._ending.end(self)

    _ending: EngineEnding = EngineShutDown()

    def end_requests(self) -> None:
        for route in self._routes.values():
            route.request.dispatched.cancel()
            route.request.reply.cancel()
        self._routes.clear()

    def end_start(self, outcome: Callable[[asyncio.Future[AttachedChild]], object]) -> None:
        if not self._child_ready.done():
            outcome(self._child_ready)

    def restart_sessions(self, failure: EditingFailure) -> None:
        for session in tuple(self._sessions.values()):
            session.engine_failed(failure)

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
            encoder: Callable[[NeovimHost, object], msgpack.ExtType] = self.handler_for(type(value))
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
        await self.ready
        while True:
            request = await self._outgoing.get()
            await request.send(self)

    def register(self, requester: NeovimRequester, request: NeovimRequest) -> None:
        self._routes[request.identity] = NeovimRoute(requester, request)

    async def bootstrap(self, requester: NeovimRequester, request: NeovimRequest) -> object:
        """Sent at once, ahead of the queue: the engine's own setup, and a session opening its buffer."""
        self.register(requester, request)
        await request.send(self)
        return await request.result()

    def enqueue(self, session: NeovimEditing, request: NeovimRequest) -> None:
        """The engine's keys and edits act on its current buffer, so a session's request
        follows its own buffer's focus. A cancelled operator stays with the buffer it began in."""
        self.focus(session)
        self._send(session, request)

    def focus(self, session: NeovimEditing) -> None:
        if self._focused is not session:
            self._focused = session
            for request in session.focus_requests():
                self._send(session, request)

    def _send(self, requester: NeovimRequester, request: NeovimRequest) -> None:
        self.register(requester, request)
        self._outgoing.put_nowait(request)

    def adopt(self, buffer: int, session: NeovimSession) -> None:
        self._sessions[buffer] = session

    async def release(self, buffer: int) -> None:
        session = self._sessions.pop(buffer, UNCLAIMED)
        if self._focused is session:
            self._focused = UNCLAIMED
        await self.bootstrap(self, NeovimCall("nvim_exec_lua", ["ToadEditor.close(...)", [buffer]]))

    def resolve_reply(self, request: NeovimRequest, reply: NeovimReply, value: object) -> None:
        reply.resolve(request, value)

    async def _start(self) -> None:
        await self._child_ready
        api = self.accept_api_info(await self.bootstrap(self, NeovimCall("nvim_get_api_info", [])))
        await self.bootstrap(self, NeovimCall("nvim_ui_attach", [*self.initial_viewport,
            {"ext_linegrid": True, "ext_cmdline": True, "ext_messages": True}]))
        script = files(toad).joinpath("neovim_editing.lua").read_text()
        await self.bootstrap(self, NeovimCall("nvim_exec_lua", [script, [api.channel]]))

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

    def resolve_route(self, identity: int, reply: NeovimReply, value: object) -> None:
        try:
            route = self._routes.pop(identity)
        except KeyError as error:
            raise NeovimWireFailure("Unexpected Neovim RPC response") from error
        route.resolve(reply, value)

    async def answer_request(self, identity: int, reply: object) -> None:
        await self.write_frame([1, identity, None, reply])


class BufferLease(ABC):
    """The buffer a session holds in an engine, and what closing the session owes it."""

    @property
    @abstractmethod
    def number(self) -> int: ...

    @abstractmethod
    async def release(self) -> None: ...


class NoBuffer(BufferLease):
    """None opened yet, or the engine that held it died and took it along: nothing to delete."""

    @property
    def number(self) -> int:
        raise NeovimWireFailure("This Neovim session has no open buffer")

    async def release(self) -> None:
        pass


NO_BUFFER = NoBuffer()


@dataclass(frozen=True)
class OpenBuffer(BufferLease):
    host: NeovimHost
    buffer: int

    @property
    def number(self) -> int:
        return self.buffer

    async def release(self) -> None:
        await self.host.release(self.buffer)


class HostsNeovim(App[object]):
    """An application that owns the one embedded Neovim its editors share."""

    @cached_property
    def neovim(self) -> NeovimHost:
        return NeovimHost(self)

    def forget_neovim(self) -> None:
        """A failed engine is never reused; the next editor that starts gets a new one."""
        self.__dict__.pop("neovim")

    @classmethod
    def serving(cls, editor: TextArea) -> NeovimHost:
        application = editor.app
        if not isinstance(application, HostsNeovim):
            raise NeovimWireFailure(f"{type(application).__name__} hosts no Neovim engine")
        return application.neovim


class NeovimEditing(VimMode, NeovimSession, HoldsBuffer):
    """One buffer session in the application's engine: its own input proof, its own paint."""

    initial_keys = ""
    map_modes: ClassVar[tuple[str, ...]] = ()

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
        self._lease: BufferLease = NO_BUFFER
        self._viewport = list(NeovimHost.initial_viewport)

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
    def boundary_state(self) -> NeovimState:
        """Neovim's own state at an engine boundary. Its expression mapping calls the
        boundary while the key is executing, so that input cannot already have a SafeState
        completion; the boundary published this snapshot from Neovim at that key."""
        return self.snapshot.state

    @property
    def allows_history_navigation(self) -> bool:
        return self.boundary_state.allows_history_navigation

    @property
    def cursor_shape(self) -> CursorShape:
        return self.snapshot.state.cursor_shape

    @property
    def binding_mode(self) -> type[EditingMode]:
        return type(self)

    @cached_property
    def _started(self) -> asyncio.Task[None]:
        editor = self._receiver.require()
        self._host = HostsNeovim.serving(editor)
        self._initial_lines = tuple(editor.document.lines)
        self._initial_selection = editor.selection
        self._lifetime = asyncio.create_task(self._write_queued(), name="Neovim session")
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
            self._receiver.project((), self.snapshot.state.cursor)
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
        await asyncio.gather(self._started, self._lifetime, return_exceptions=True)
        await self._lease.release()

    async def _write_queued(self) -> None:
        """Requests made before this buffer exists wait for it, in the order they were made."""
        await self._started
        while True:
            self._host.enqueue(self, await self._outgoing.get())

    @property
    def buffer(self) -> int:
        return self._lease.number

    def _register(self, request: NeovimRequest) -> None:
        request.reply.add_done_callback(self._observe_failure)
        request.dispatched.add_done_callback(self._observe_failure)
        self.snapshot.state.raise_failure()
        self._pending[request.identity] = request

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
        return self._enqueue(NeovimOperation(self, self._next_generation(), method, arguments))

    def _lua(self, code: str, arguments: Sequence[object]) -> asyncio.Future[object]:
        return self._enqueue(NeovimLuaOperation(self, self._next_generation(), code, arguments))

    def _input(self, keys: str) -> asyncio.Future[object]:
        return self._enqueue(NeovimInput(self, self._next_generation(), keys))

    # Escape is the person's key: Neovim offers it back at the Standard boundary.
    # The application reaches Normal from any mode with Neovim's own CTRL-\ CTRL-N,
    # on the same ordered input path, so its keys never reach that boundary.
    to_normal = "<C-\\><C-N>"

    def focus_requests(self) -> tuple[NeovimRequest, ...]:
        """Take the engine's window: the buffer it leaves keeps its mode and cursor for its
        return, and CTRL-\\ CTRL-N cancels any operator or command line it left pending, so
        this buffer's first key can never complete another buffer's command. The engine's one
        UI then takes this prompt's size, so motions over wrapped lines use its width."""
        requests = (NeovimInput(self, self._next_generation(),
                                f"<Cmd>lua ToadEditor.leave()<CR>{self.to_normal}"
                                f"<Cmd>lua ToadEditor.enter({self.buffer})<CR>"),
                    NeovimCall("nvim_ui_try_resize", self._viewport))
        for request in requests:
            self._register(request)
        return requests

    async def _start(self) -> None:
        host = self._host
        await host.ready
        editor = self._receiver.require()
        initial_lines = self._initial_lines
        initial_cursor = self._initial_selection.end
        mappings: list[list[object]] = []
        self._boundaries = []
        # One buffer crosses every Neovim mode, so each mode takes its own profile's keys.
        for profile in NeovimEditing.__subclasses__():
            for key, binding in editor.binding_map(profile):
                for spelling, native in binding.declared_key.input_bindings(key):
                    index = len(self._boundaries)
                    self._boundaries.append(binding)
                    mappings.append([self.input_code(spelling), self.input_code(native), index,
                                     list(profile.map_modes)])
        self._lease = OpenBuffer(host, FieldCodec.decode(int, await host.bootstrap(self, NeovimCall(
            "nvim_exec_lua", ["return ToadEditor.open(...)",
                              [list(initial_lines), list(initial_cursor), editor.indent_width, mappings]]))))
        host.adopt(self.buffer, self)
        self._viewport = self.viewport(editor)
        # The opening requests go ahead of anything queued while the buffer was being made.
        host.focus(self)
        opening: tuple[NeovimRequest, ...] = ()
        if self.initial_keys:
            opening = (NeovimInput(self, self._next_generation(), self.initial_keys),
                       NeovimLuaOperation(self, self._next_generation(),
                                          "return ToadEditor.cursor(...)", [initial_cursor]))
        for request in opening:
            self._register(request)
            host.enqueue(self, request)

    def resolve_reply(self, request: NeovimRequest, reply: NeovimReply, value: object) -> None:
        reply.resolve(request, value)
        self._pending.pop(request.identity, None)
        # SafeState can arrive before the final RPC response. Its
        # publication and that response must invalidate the same view owner.
        if self.completed:
            self.request_paint()

    def engine_boundary(self, boundary: int, display: NeovimDisplay) -> bool:
        if not 0 <= boundary < len(self._boundaries):
            raise NeovimWireFailure("Unknown Neovim cursor boundary")
        self.publish(self.snapshot.with_boundary(display))
        self._receiver.visit(self.render)
        return self._receiver.boundary(self._boundaries[boundary])

    def accept_lines(self, change: NeovimLineChange) -> None:
        if change.last == -1:
            self._changes.append(NeovimBufferTransfer(change.lines))
        else:
            self._changes.append(change)
        self.snapshot = self.snapshot.with_lines()

    def accept_display(self, display: NeovimDisplay) -> None:
        self.publish(self.snapshot.with_display(display))

    def engine_failed(self, error: EditingFailure) -> None:
        """The engine died with this buffer in it. The prompt still shows the last text it
        painted, so the buffer reopens in a new engine from that; input in flight is lost,
        never replayed, and the tab says so."""
        self._lease = NO_BUFFER
        self._pending.clear()
        self._changes.clear()
        self._lifetime.cancel()
        del self._started
        # Not published: projecting the starting state would move the prompt's cursor to its
        # default before the reopened buffer reads where the cursor really is.
        self.snapshot = StartingState().snapshot()
        self.request_paint()
        def reopen(editor: TextArea) -> None:
            editor.notify(f"{error}. Neovim restarted from the text on screen; "
                          "input it had not finished was not replayed.",
                          title="Neovim restarted", severity="warning")
            self.attach(editor)
        self._receiver.visit(reopen)

    def publish(self, snapshot: NeovimSnapshot) -> None:
        """Project preceding lines before exposing the display that describes them."""
        changes, self._changes = self._changes, []
        self._receiver.project(changes, snapshot.state.cursor)
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
        """Queue input; the existing request owner observes its reply and failure."""
        self._input(self.input_code(event.key, event.character or ""))
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

    @staticmethod
    def viewport(editor: TextArea) -> list[int]:
        return [max(1, editor.wrap_width), max(3, editor.content_size.height + 2)]

    def resize(self, editor: TextArea) -> None:
        # This UI API is RPC-only, like nvim_ui_attach during startup. A
        # viewport resize is not a buffer edit and must not advance its generation.
        self._viewport = self.viewport(editor)
        self._enqueue(NeovimCall("nvim_ui_try_resize", self._viewport))

    def enter_text(self, editor: TextArea) -> None:
        self._input(self.to_normal + "i")

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
            self._input(self.to_normal)
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
