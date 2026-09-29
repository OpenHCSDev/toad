"""ACP terminal requests address operational executions, never mounted widgets."""
from weakref import ref
from agent_comms.declared_family import DeclaredFamily

class TerminalSessionRetired(RuntimeError):
    pass

class TerminalControllerState(DeclaredFamily, affix="TerminalControllerState"):
    accepts_create = False

class OpenTerminalControllerState(TerminalControllerState):
    accepts_create = True

class RetiredTerminalControllerState(TerminalControllerState):
    pass

from toad.terminal_execution import Command, TerminalExecution, ToolState
from toad.widgets.terminal_tool import TerminalTool


class TerminalController:
    def __init__(self) -> None:
        self.executions: dict[str, TerminalExecution] = {}
        self.state = OpenTerminalControllerState()
        self._next_id = 0
        self._target = lambda: None

    async def create(self, command: Command, output_byte_limit: int | None) -> str:
        state = self.state
        if not state.accepts_create:
            raise TerminalSessionRetired("ACP terminal session is retired")
        self._next_id += 1
        terminal_id = f"terminal-{self._next_id}"
        execution = TerminalExecution(command, output_byte_limit)
        self.executions[terminal_id] = execution
        target = self._target()
        width, height = target.get_terminal_dimensions() if target is not None else (80, 24)
        try:
            await execution.start(width, height)
        except Exception:
            await execution.close()
            self.executions.pop(terminal_id, None)
            raise
        if self.state is not state:
            await execution.close()
            self.executions.pop(terminal_id, None)
            raise TerminalSessionRetired("ACP terminal session retired during creation")
        await self._present(terminal_id, execution)
        return terminal_id

    async def _present(self, terminal_id: str, execution: TerminalExecution) -> None:
        target = self._target()
        if target is None or target._closing or target.query_one_optional(f"#{terminal_id}"):
            return
        terminal = TerminalTool(execution, id=terminal_id)
        await target.post(terminal)
        if self._target() is not target:
            await terminal.remove()

    async def attach(self, target) -> None:
        self._target = ref(target)
        for terminal_id, execution in tuple(self.executions.items()):
            await self._present(terminal_id, execution)

    def detach(self) -> None:
        self._target = lambda: None
        for execution in self.executions.values():
            execution.detach()

    def require(self, terminal_id: str) -> TerminalExecution:
        execution = self.executions[terminal_id]
        if execution.released:
            raise KeyError(f"Released terminal {terminal_id!r}")
        return execution

    def output(self, terminal_id: str) -> ToolState:
        return self.require(terminal_id).tool_state

    async def wait(self, terminal_id: str) -> tuple[int | None, str | None]:
        return await self.require(terminal_id).wait_for_exit()

    def kill(self, terminal_id: str) -> None:
        self.require(terminal_id).kill()

    def release(self, terminal_id: str) -> None:
        execution = self.require(terminal_id)
        execution.kill()
        execution.release()

    async def retire(self, terminal_id) -> None:
        execution = self.executions.pop(terminal_id, None)
        if execution is not None:
            await execution.close()

    async def close(self) -> None:
        self.state = RetiredTerminalControllerState()
        self.detach()
        for execution in tuple(self.executions.values()):
            await execution.close()
        self.executions.clear()
