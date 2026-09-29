"""Operational terminal execution; optional widgets do not own ACP processes."""
from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
import codecs
import fcntl
import os
import pty
import shlex
import signal
import struct
import termios
from typing import Mapping
from weakref import ref

from agent_comms.child_process import STOP_GRACE_SECONDS
from toad import ansi
from toad.shell_read import shell_read

@dataclass
class Command:
    """A command and corresponding environment."""

    command: str
    """Command to run."""
    args: list[str]
    """List of arguments."""
    env: Mapping[str, str]
    """Environment variables."""
    cwd: str
    """Current working directory."""

    def __str__(self) -> str:
        command_str = shlex.join([self.command, *self.args]).strip("'")
        return command_str


@dataclass
class ToolState:
    """Current state of the terminal."""

    output: str
    truncated: bool
    return_code: int | None = None
    signal: str | None = None

    @property
    def finished(self) -> bool:
        """Whether this execution ended normally or by a signal."""
        return self.return_code is not None or self.signal is not None

    @classmethod
    def capture(cls, output: str, truncated: bool, return_code: int | None) -> ToolState:
        """Decode the operating system's negative signal return code once."""
        if return_code is not None and return_code < 0:
            return cls(output, truncated, signal=signal.Signals(-return_code).name)
        return cls(output, truncated, return_code=return_code)


class TerminalExecution:
    """The original command, ANSI model, bounded ACP output and process lifecycle."""

    def __init__(self, command: Command, output_byte_limit: int | None = None) -> None:
        self._command = command
        self._output_byte_limit = output_byte_limit
        self._command_task: asyncio.Task | None = None
        self._output: deque[bytes] = deque()
        self._process: Process | None = None
        self._bytes_read = 0
        self._output_bytes_count = 0
        self._shell_fd: int | None = None
        self._return_code: int | None = None
        self._released = False
        self._ready_event = asyncio.Event()
        self._exit_event = asyncio.Event()
        self._startup_error: Exception | None = None
        self.state = ansi.TerminalState(self.write_stdin)
        self._view = lambda: None

    @property
    def command(self) -> Command:
        return self._command

    def attach(self, terminal) -> None:
        self._view = ref(terminal)
        terminal.set_state(self.state)
        terminal.set_write_to_stdin(self.write_stdin)
        self.project()

    def detach(self, terminal=None) -> None:
        if terminal is None or self._view() is terminal:
            self._view = lambda: None

    def update_size(self, width: int, height: int) -> None:
        self.state.update_size(width, height)
        if self._shell_fd is not None:
            with suppress(OSError):
                self.resize_pty(self._shell_fd, width, height)

    def project(self) -> None:
        if (terminal := self._view()) is not None and terminal.is_attached:
            terminal.present_execution()

    async def close(self) -> None:
        self.detach()
        self.kill()
        if self._command_task is not None:
            try:
                async with asyncio.timeout(STOP_GRACE_SECONDS):
                    await asyncio.shield(self._command_task)
            except TimeoutError:
                self._command_task.cancel()
                await asyncio.gather(self._command_task, return_exceptions=True)
        if self._process is not None:
            await self._process.wait()

    @property
    def return_code(self) -> int | None:
        """The command return code, or `None` if not yet set."""
        return self._return_code

    @property
    def released(self) -> bool:
        """Has the terminal been released?"""
        return self._released

    @property
    def tool_state(self) -> ToolState:
        """Get the current terminal state."""
        output, truncated = self.get_output()
        return ToolState.capture(output, truncated, self.return_code)

    @staticmethod
    def resize_pty(fd: int, columns: int, rows: int) -> None:
        """Resize the pseudo terminal.

        Args:
            fd: File descriptor.
            columns: Columns (width).
            rows: Rows (height).
        """
        # Pack the dimensions into the format expected by TIOCSWINSZ
        size = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

    async def wait_for_exit(self) -> tuple[int | None, str | None]:
        """Wait for the terminal process to exit."""
        if self._process is None or self._command_task is None:
            return None, None
        # await self._task
        await self._exit_event.wait()
        state = self.tool_state
        return state.return_code, state.signal

    def kill(self) -> bool:
        """Kill the terminal process.

        Returns:
            Returns `True` if the process was killed, or `False` if there
                was no running process.
        """
        if self.return_code is not None:
            return False
        if self._process is None:
            return False
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except Exception:
            return False
        return True

    def release(self) -> None:
        """Release the terminal (may no longer be used from ACP)."""
        self._released = True

    async def start(self, width: int = 0, height: int = 0) -> None:
        assert self._command is not None

        self.state.update_size(width or 80, height or 24)
        self._command_task = asyncio.create_task(
            self.run(), name=f"Terminal {self._command}"
        )
        await self._ready_event.wait()
        if self._startup_error is not None:
            raise self._startup_error

    async def run(self) -> None:
        try:
            await self._run()
        except Exception as error:
            self._startup_error = error
        finally:
            self._ready_event.set()
            self._exit_event.set()
            self.project()

    async def _run(self) -> None:
        self._command_task = asyncio.current_task()

        assert self._command is not None
        master, slave = pty.openpty()
        self._shell_fd = master

        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        command = self._command
        environment = os.environ | command.env

        if " " in command.command:
            run_command = command.command
        else:
            run_command = f"{command.command} {shlex.join(command.args)}"

        shell = os.environ.get("SHELL", "sh")
        run_command = shlex.join([shell, "-c", run_command])

        try:
            process = self._process = await asyncio.create_subprocess_shell(
                run_command,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=environment,
                cwd=command.cwd,
                start_new_session=True,
            )
        except Exception as error:
            self._ready_event.set()
            os.close(slave)
            os.close(master)
            self._shell_fd = None
            raise

        self._ready_event.set()

        self.resize_pty(
            master,
            self.state.width,
            self.state.height,
        )

        os.close(slave)

        BUFFER_SIZE = 64 * 1024 * 2
        reader = asyncio.StreamReader(BUFFER_SIZE)
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        transport, _ = await loop.connect_read_pipe(
            lambda: protocol, os.fdopen(master, "rb", 0)
        )
        # Create write transport
        writer_protocol = asyncio.BaseProtocol()
        write_transport, _ = await loop.connect_write_pipe(
            lambda: writer_protocol,
            os.fdopen(os.dup(master), "wb", 0),
        )
        self.writer = write_transport

        unicode_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                data = await shell_read(reader, BUFFER_SIZE)
                if process_data := unicode_decoder.decode(data, final=not data):
                    self._record_output(data)
                    await self.state.write(process_data)
                    self.project()
                if not data:
                    break
        finally:
            transport.close()
            write_transport.close()
            self._shell_fd = None

        self._return_code = await process.wait()
        self.state.show_cursor = False
        self.project()

    async def write_stdin(self, text: str | bytes, hide_echo: bool = False) -> int:
        if self._shell_fd is None:
            return 0
        text_bytes = text.encode("utf-8", "ignore") if isinstance(text, str) else text
        try:
            return await asyncio.to_thread(os.write, self._shell_fd, text_bytes)
        except OSError:
            return 0

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
            output_bytes = output_bytes[-self._output_byte_limit :]
            # Must start on a utf-8 boundary
            # Discard initial bytes that aren't a utf-8 continuation byte.
            for offset, byte_value in enumerate(output_bytes):
                if not is_continuation(byte_value):
                    if offset:
                        output_bytes = output_bytes[offset:]
                    break

        output = output_bytes.decode("utf-8", "replace")
        return output, truncated
