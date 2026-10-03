"""Original PTY custody and nominal outcomes; mounted views are projections."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections import deque
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
import codecs
import os
import pty
import shlex
import signal
import termios
from io import FileIO
from typing import Mapping
from weakref import ref

from acp import schema as protocol
from agent_comms.child_process import (
    AttachedChild, TerminalChildStdio, ChildOutcome, ExitedOutcome, SignaledOutcome,
    join_retirement,
)
from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import MroDispatch, handles
from toad import ansi
from toad.shell_read import shell_read
from toad.terminal_environment import TerminalEnvironment

@dataclass
class Command:
    """A command and corresponding environment."""

    script: str
    """One compiled shell invocation; never reclassified from its text."""
    env: Mapping[str, str]
    """Environment variables."""
    cwd: str | None
    """Current working directory."""
    shell: str = field(default_factory=lambda: TerminalEnvironment.login_shell(os.environ), kw_only=True)
    """Original launch shell; catalog scripts explicitly select /bin/sh."""

    @classmethod
    def for_script(cls, script: str, *, env: Mapping[str, str] | None = None,
                   cwd: str | None = None) -> Command:
        """Catalog shell scripts use the standard shell and terminal environment."""
        return cls(script, TerminalEnvironment.for_child(os.environ) | (env or {}),
                   cwd, shell="/bin/sh")

    @classmethod
    def for_argv(cls, command: str, args: list[str], *,
                 env: Mapping[str, str], cwd: str) -> Command:
        """Compile ACP executable/arguments exactly once at its typed boundary."""
        return cls(shlex.join([command, *args]), env, cwd)

    @property
    def shell_command(self) -> tuple[str, str, str]:
        return self.shell, "-c", self.script

    def __str__(self) -> str:
        return self.script


class TerminalOutcome(DeclaredFamily, affix="TerminalOutcome"):
    finished = False
    successful = False

    @property
    def return_code(self) -> int | None:
        return None  # No POSIX completion yet; derived, never retained in a view.

    def exit_status(self) -> protocol.TerminalExitStatus | None:
        return None  # Official ACP absence, never an internal lifecycle field.

class RunningTerminalOutcome(TerminalOutcome):
    """The original execution task has not returned a completion witness."""


class UnstartedTerminalOutcome(TerminalOutcome):
    """The original execution has not acquired a job yet."""


class RetiredTerminalOutcome(TerminalOutcome):
    """Acquisition was revoked before any command could start."""
    finished = True


class TerminalCompletion(TerminalOutcome):
    finished = True

    @abstractmethod
    def wait_response(self) -> protocol.WaitForTerminalExitResponse: ...

    @property
    @abstractmethod
    def return_code(self) -> int: ...

    @property
    @abstractmethod
    def label(self) -> str: ...

    @classmethod
    def capture(cls, original: ChildOutcome) -> TerminalCompletion:
        # Existing child owner decodes the operating system once. The
        # terminal projection retains that ORIGINAL rich value, never scalars.
        return _TerminalCompletionDecoder(original).completion


@dataclass(frozen=True)
class ExitedTerminalOutcome(TerminalCompletion):
    original: ExitedOutcome

    @property
    def successful(self) -> bool:
        return self.original.successful

    @property
    def label(self) -> str:
        return str(self.original.code)

    @property
    def return_code(self) -> int:
        return self.original.code

    def exit_status(self):
        return protocol.TerminalExitStatus(exit_code=self.original.code)

    def wait_response(self):
        return protocol.WaitForTerminalExitResponse(exit_code=self.original.code)


@dataclass(frozen=True)
class SignaledTerminalOutcome(TerminalCompletion):
    original: SignaledOutcome

    @property
    def label(self) -> str:
        return signal.Signals(self.original.signal_number).name

    @property
    def return_code(self) -> int:
        return -self.original.signal_number

    def exit_status(self):
        return protocol.TerminalExitStatus(signal=self.label)

    def wait_response(self):
        return protocol.WaitForTerminalExitResponse(signal=self.label)


class _TerminalCompletionDecoder(MroDispatch):
    """Typed original POSIX members enter the terminal family at acquisition."""
    completion: TerminalCompletion

    def __init__(self, original):
        self.dispatch_sync(original)

    @handles(ExitedOutcome)
    def exited(self, original):
        self.completion = ExitedTerminalOutcome(original)

    @handles(SignaledOutcome)
    def signaled(self, original):
        self.completion = SignaledTerminalOutcome(original)


@dataclass(frozen=True)
class FailedTerminalOutcome(TerminalOutcome):
    error: BaseException
    finished = True

@dataclass(frozen=True)
class ToolState:
    output: str
    truncated: bool
    outcome: TerminalOutcome

    def response(self):
        return protocol.TerminalOutputResponse(output=self.output, truncated=self.truncated,
                                               exit_status=self.outcome.exit_status())


@dataclass(frozen=True)
class PtyProcess:
    """Complete acquired handles, scoped by the execution's AsyncExitStack."""
    child: AttachedChild
    master: FileIO
    reader: asyncio.StreamReader

    @classmethod
    async def acquire(cls, command: tuple[str, ...], *, env, cwd, width, height,
                      custody: AsyncExitStack, buffer_size=128 * 1024):
        master, slave = pty.openpty()
        master_file = custody.enter_context(os.fdopen(master, "rb", 0))
        slave_file = custody.enter_context(os.fdopen(slave, "wb", 0))
        os.set_blocking(master, False)
        # The child can query its geometry immediately after exec.
        cls.resize_fd(master, width, height)

        reader = asyncio.StreamReader(buffer_size)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: protocol, master_file,
        )
        custody.callback(transport.close)

        async def acquire_child():
            child = await AttachedChild.start(
                command, stdio=TerminalChildStdio(slave_file), env=env, cwd=cwd,
            )
            custody.push_async_callback(child.stop)
            return child

        spawn = asyncio.create_task(acquire_child())
        try:
            child = await asyncio.shield(spawn)
        except asyncio.CancelledError:
            # Register the SAME child before releasing its descriptors, even
            # when cancellation races the operating system's actual spawn.
            await join_retirement(spawn)
            raise
        slave_file.close()
        return cls(child, master_file, reader)

    def resize(self, width, height):
        with suppress(OSError, ValueError):
            self.resize_fd(self.master.fileno(), width, height)

    @staticmethod
    def resize_fd(fd, width, height):
        termios.tcsetwinsize(fd, (height, width))

    async def write(self, data: bytes) -> int:
        # Nonblocking owned FD is consumed on this loop, not by a delayed
        # thread that could write to an unrelated reused descriptor.
        try:
            return os.write(self.master.fileno(), data)
        except (OSError, ValueError):
            return 0

    def kill(self) -> None:
        self.child.force()

    async def close(self):
        await self.child.stop()


class TerminalOperation(DeclaredFamily, affix="TerminalOperation"):
    def retire(self) -> TerminalOperation:
        return self

    @abstractmethod
    def outcome(self) -> TerminalOutcome: ...

    def kill(self) -> None:
        pass

    def resize(self, width, height):
        pass

    async def write(self, data):
        return 0

    async def close(self):
        pass

    async def wait(self) -> TerminalCompletion:
        raise RuntimeError("Terminal execution has not started")

    async def custody(self) -> PtyProcess:
        raise RuntimeError("Terminal execution has no acquired PTY")

    @abstractmethod
    def start(self, execution) -> ActiveTerminalOperation: ...


class NewTerminalOperation(TerminalOperation):
    def outcome(self):
        return UnstartedTerminalOutcome()

    def retire(self):
        return RetiredTerminalOperation()

    def start(self, execution):
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(execution.run(ready), name=type(execution).__name__)
        operation = ActiveTerminalOperation(task, ready)
        task.add_done_callback(operation.settle_startup)
        return operation


class RetiredTerminalOperation(TerminalOperation):
    def outcome(self):
        return RetiredTerminalOutcome()

    def start(self, execution):
        raise RuntimeError("Terminal execution was retired before startup")


@dataclass(frozen=True)
class ActiveTerminalOperation(TerminalOperation):
    task: asyncio.Task[TerminalCompletion]
    ready: asyncio.Future[PtyProcess]

    def start(self, execution):
        raise RuntimeError("Terminal execution already started")

    def settle_startup(self, task):
        # A cancelled task may never enter run(), so its original cancellation
        # must settle the startup waiter too. Entered failures settle in run().
        if task.cancelled() and not self.ready.done():
            self.ready.cancel()

    def outcome(self):
        if not self.task.done():
            return RunningTerminalOutcome()
        if self.task.cancelled():
            return FailedTerminalOutcome(asyncio.CancelledError())
        try:
            return self.task.result()
        except BaseException as error:
            return FailedTerminalOutcome(error)

    def resize(self, width, height):
        if self.ready.done() and not self.task.done():
            self.ready.result().resize(width, height)

    async def write(self, data):
        if self.ready.done() and not self.task.done():
            return await self.ready.result().write(data)
        return 0

    def kill(self) -> None:
        if self.task.done():
            return
        if not self.ready.done():
            self.task.cancel()
            return
        self.ready.result().kill()

    async def wait(self):
        # Cancellation of an ACP waiter is not command cancellation.
        return await asyncio.shield(self.task)

    async def custody(self):
        return await asyncio.shield(self.ready)

    async def close(self):
        await join_retirement(asyncio.create_task(self.retire_task()))

    async def retire_task(self):
        if self.task.done():
            await asyncio.gather(self.task, return_exceptions=True)
            return
        if not self.ready.done():
            self.task.cancel()
        else:
            await self.ready.result().close()
        # Original execution failure belongs to task/outcome; joining does not
        # consume a second success/failure state or suppress cleanup failure.
        await asyncio.gather(self.task, return_exceptions=True)


class TerminalExecution:
    """One ANSI/output owner and one acquired operation, independent of views."""
    def __init__(self, command: Command, output_byte_limit: int | None = None, *,
                 width: int = ansi.TerminalState.DEFAULT_WIDTH,
                 height: int = ansi.TerminalState.DEFAULT_HEIGHT,
                 state: ansi.TerminalState | None = None):
        self._command = command
        self._output_byte_limit = output_byte_limit
        self._output: deque[bytes] = deque()
        self._bytes_read = 0
        self._output_bytes_count = 0
        self._operation: TerminalOperation = NewTerminalOperation()
        # An existing ANSI resource retains prefixes and sequential command output.
        self.state = (ansi.TerminalState(self.write_stdin, width=width, height=height)
                      if state is None else state)
        self._view = lambda: None

    @property
    def command(self):
        return self._command

    @property
    def outcome(self):
        return self._operation.outcome()

    @property
    def tool_state(self):
        output, truncated = self.get_output()
        return ToolState(output, truncated, self.outcome)

    def attach(self, terminal):
        self._view = ref(terminal)
        terminal.set_state(self.state)
        terminal.set_write_to_stdin(self.write_stdin)
        self.project(None, None)

    def detach(self, terminal=None):
        if terminal is None or self._view() is terminal:
            self._view = lambda: None

    def project(self, scrollback: set[int] | None, alternate: set[int] | None):
        if (terminal := self._view()) is not None and terminal.is_attached:
            terminal.present_execution(scrollback, alternate)

    def update_size(self, width, height):
        self.state.update_size(width, height)
        self._operation.resize(width, height)

    async def close(self):
        self.detach()
        # Active acquisition already revokes another start. Only a never-started
        # operation needs retirement; retain the SAME active task while joining.
        self._operation = self._operation.retire()
        await self._operation.close()

    def kill(self) -> None:
        self._operation.kill()

    async def wait_for_exit(self):
        return await self._operation.wait()

    async def custody(self) -> PtyProcess:
        """Observe the SAME original acquired resource, never a copied PID/status."""
        return await self._operation.custody()

    async def start(self):
        operation = self._operation.start(self)
        self._operation = operation
        self.state.bind_stdin(self.write_stdin)
        self.state.show_cursor = True
        await asyncio.shield(operation.ready)

    async def run(self, ready):
        try:
            async with AsyncExitStack() as custody:
                command = self.command
                acquired = await PtyProcess.acquire(
                    command.shell_command, env=os.environ | command.env, cwd=command.cwd,
                    width=self.state.width, height=self.state.height, custody=custody,
                )
                ready.set_result(acquired)
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    data = await shell_read(acquired.reader, 128 * 1024)
                    self._record_output(data)  # Preserve partial UTF-8 bytes too.
                    if decoded := decoder.decode(data, final=not data):
                        scrollback, alternate = await self.state.write(decoded)
                        self.project(scrollback, alternate)
                    if not data:
                        break
                return TerminalCompletion.capture(await acquired.child.wait())
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise
        finally:
            self.state.show_cursor = False
            # The task's result becomes authoritative only after this returns.
            asyncio.get_running_loop().call_soon(self.project, None, None)

    async def write_stdin(self, text: str | bytes, hide_echo=False):
        data = text.encode("utf-8", "ignore") if isinstance(text, str) else text
        return await self._operation.write(data)

    def _record_output(self, data: bytes) -> None:
        """Keep a record of the bytes left.

        Store at most the limit set in self._output_byte_limit (if set).

        """

        self._output.append(data)
        self._output_bytes_count += len(data)
        self._bytes_read += len(data)

        if self._output_byte_limit is None:
            return

        while self._output_bytes_count > self._output_byte_limit and self._output:
            oldest_bytes = self._output[0]
            oldest_bytes_count = len(oldest_bytes)
            if self._output_bytes_count - oldest_bytes_count < self._output_byte_limit:
                break
            self._output.popleft()
            self._output_bytes_count -= oldest_bytes_count

    def get_output(self) -> tuple[str, bool]:
        """Get the output.

        Returns:
            A tuple of the output and a bool to indicate if the output was truncated.
        """
        output_bytes = b"".join(self._output)

        def is_continuation(byte_value: int) -> bool:
            """Check if the given byte is a utf-8 continuation byte.

            Args:
                byte_value: Ordinal of the byte.

            Returns:
                `True` if the byte is a continuation, or `False` if it is the start of a character.
            """
            return (byte_value & 0b11000000) == 0b10000000

        truncated = self._bytes_read > len(output_bytes)
        if (
            self._output_byte_limit is not None
            and len(output_bytes) > self._output_byte_limit
        ):
            truncated = True
            output_bytes = output_bytes[len(output_bytes) - self._output_byte_limit :]
            # Must start on a utf-8 boundary
            # Discard initial bytes that aren't a utf-8 continuation byte.
            for offset, byte_value in enumerate(output_bytes):
                if not is_continuation(byte_value):
                    if offset:
                        output_bytes = output_bytes[offset:]
                    break
            else:
                output_bytes = b""  # No complete leading code point fits the bound.

        output = output_bytes.decode("utf-8", "replace")
        return output, truncated
