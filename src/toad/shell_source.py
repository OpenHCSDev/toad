"""Shared shell process ownership, independent of how commands start."""
from abc import ABC, abstractmethod
import asyncio
import psutil
from toad.surface_binding import SurfaceBinding, DetachedSurfaceBinding
from toad.core.events import CoreEventStream
from toad.shell_output import ShellOutput, CurrentShellOutput, NoCurrentShellOutput
from toad.terminal_execution import TerminalOperation, NewTerminalOperation


class ShellOperationalSource(ABC):
    def __init__(self, terminal_size: tuple[int, int]) -> None:
        self.events = CoreEventStream(self)
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.outputs: list[ShellOutput] = []
        self.output: CurrentShellOutput = NoCurrentShellOutput()
        self._presentation_lock = asyncio.Lock()
        self._terminal_size = terminal_size
        self.operation: TerminalOperation = NewTerminalOperation()

    @abstractmethod
    async def _run_pty(self, ready): ...

    @abstractmethod
    async def write(
        self, text: str | bytes, hide_echo: bool = False, hide_output: bool = False
    ) -> int: ...

    async def is_busy(self) -> bool:
        """Observe the children of this SAME acquired shell incarnation."""
        process = await self.operation.process()

        def children():
            if not process.child.alive():
                return False
            try:
                return bool(psutil.Process(process.child.pid).children(recursive=True))
            except psutil.NoSuchProcess, psutil.AccessDenied:
                return False

        return await asyncio.to_thread(children)

    async def send_input(self, text: str, paste: bool = False) -> None:
        await self.wait_for_ready()
        text = self.output.format_input(text, paste)
        await self.write(f"{text}\n", hide_echo=True)

    @property
    def is_finished(self) -> bool:
        return self.operation.outcome().finished

    async def wait_for_ready(self) -> None:
        await self.operation.process()

    def focus_output(self) -> None:
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
        self.operation = self.operation.retire()
        await self.operation.close()
        self.outputs.clear()
        self.output = NoCurrentShellOutput()

    async def run(self, ready):
        try:
            return await self._run_pty(ready)
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            if isinstance(error, Exception):
                self.surface.shell_failed(error)
            raise
