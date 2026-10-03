"""Shared operational shell custody, independent of command/start behavior."""
from abc import ABC, abstractmethod
import asyncio
from toad.surface_binding import SurfaceBinding, DetachedSurfaceBinding
from toad.core.events import CoreEventStream
from toad.shell_output import ShellOutput, ShellTerminalOutput
from toad.terminal_execution import TerminalOperation, NewTerminalOperation


class ShellOperationalSource(ABC):
    def __init__(self, terminal_size: tuple[int, int]) -> None:
        self.events = CoreEventStream(self)
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.outputs: list[ShellOutput] = []
        self.output: ShellTerminalOutput | None = None
        self._presentation_lock = asyncio.Lock()
        self._terminal_size = terminal_size
        self._operation: TerminalOperation = NewTerminalOperation()

    @abstractmethod
    async def _run_pty(self, ready): ...

    @property
    def is_finished(self) -> bool:
        return self._operation.outcome().finished

    async def wait_for_ready(self) -> None:
        await self._operation.custody()

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
        self._operation = self._operation.retire()
        await self._operation.close()
        self.outputs.clear()
        self.output = None

    async def run(self, ready):
        try:
            return await self._run_pty(ready)
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            if isinstance(error, Exception):
                self.surface.shell_failed(error)
            raise
