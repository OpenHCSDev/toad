"""Shared operational shell custody, independent of command/start behavior."""
from abc import ABC, abstractmethod
import asyncio
from contextlib import suppress
import os
import signal
from agent_comms.child_process import STOP_GRACE_SECONDS
from toad.surface_binding import SurfaceBinding, DetachedSurfaceBinding
from toad.core.events import CoreEventStream
from toad.shell_output import ShellOutput, ShellTerminalOutput


class ShellOperationalSource(ABC):
    def __init__(self, terminal_size: tuple[int, int]) -> None:
        self.events = CoreEventStream(self)
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.outputs: list[ShellOutput] = []
        self.output: ShellTerminalOutput | None = None
        self._presentation_lock = asyncio.Lock()
        self._terminal_size = terminal_size
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

    async def attach(self, binding: SurfaceBinding) -> None:
        async with self._presentation_lock:
            self.surface.close()
            for output in self.outputs:
                output.detach()
            self.surface = binding
            binding.prepare_shell(self)
            for output in self.outputs:
                await binding.present_shell(output)

    async def detach(self) -> None:
        async with self._presentation_lock:
            self.surface.close()
            self.surface = DetachedSurfaceBinding()
            for output in self.outputs:
                output.detach()

    async def _present(self, output: ShellOutput) -> None:
        async with self._presentation_lock:
            await self.surface.present_shell(output)

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
