"""Shared operational shell custody, independent of command/start behavior."""
from abc import ABC, abstractmethod
import asyncio
from contextlib import suppress
import os
import signal
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.child_process import STOP_GRACE_SECONDS
from toad.shell_output import ShellOutput, ShellTerminalOutput

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class ShellOperationalSource(ABC):
    def __init__(self, conversation: "Conversation") -> None:
        self._conversation = ref(conversation)
        self._app = conversation.app
        self.outputs: list[ShellOutput] = []
        self.output: ShellTerminalOutput | None = None
        self._presentation_lock = asyncio.Lock()
        self._terminal_size = conversation.get_terminal_dimensions()
        self.master: int | None = None
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._transport: asyncio.ReadTransport | None = None
        self._finished = False

    @abstractmethod
    async def _run_pty(self) -> None: ...

    def focus_output(self) -> None:
        if self.output is not None:
            self.output.focus()

    async def attach(self, conversation: "Conversation") -> None:
        async with self._presentation_lock:
            self._conversation = ref(conversation)
            conversation.working_directory = self.working_directory
            for output in self.outputs:
                await output.present(conversation)

    async def detach(self) -> None:
        async with self._presentation_lock:
            self._conversation = lambda: None
            for output in self.outputs:
                output.detach()

    async def _present(self, output: ShellOutput) -> None:
        async with self._presentation_lock:
            if (conversation := self._conversation()) is not None:
                await output.present(conversation)

    async def close(self) -> None:
        """Closing a logical session ends its owned PTY; UI retirement does not."""
        await self.detach()
        if self._process is not None and self._process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(self._process.pid, signal.SIGTERM)
            try:
                async with asyncio.timeout(STOP_GRACE_SECONDS):
                    await self._process.wait()
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(self._process.pid, signal.SIGKILL)
                await self._process.wait()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self.outputs.clear()
        self.output = None

    async def run(self) -> None:
        try:
            await self._run_pty()
        finally:
            if self._transport is not None:
                self._transport.close()
                self._transport = None
            elif self.master is not None:
                with suppress(OSError):
                    os.close(self.master)
            self.master = None
            self._finished = True

