"""ACP terminal requests address operational executions, never mounted widgets."""
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.child_process import join_retirement
import asyncio

class TerminalSessionRetired(RuntimeError):
    pass

class TerminalControllerState(DeclaredFamily, affix="TerminalControllerState"):
    @abstractmethod
    def require_create(self): ...

    def owns_projection(self, executions, terminal_id, execution):
        return False

class OpenTerminalControllerState(TerminalControllerState):
    def require_create(self):
        pass

    def owns_projection(self, executions, terminal_id, execution):
        return executions.get(terminal_id) is execution

class RetiredTerminalControllerState(TerminalControllerState):
    def require_create(self):
        raise TerminalSessionRetired("ACP terminal session is retired")

from toad.terminal_execution import Command, TerminalExecution, ToolState


class TerminalController:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.executions: dict[str, TerminalExecution] = {}
        self.state = OpenTerminalControllerState()
        self._next_id = 0

    async def create(self, command: Command, output_byte_limit: int | None) -> str:
        state = self.state
        state.require_create()
        self._next_id += 1
        terminal_id = f"terminal-{self._next_id}"
        execution = TerminalExecution(command, output_byte_limit)
        self.executions[terminal_id] = execution
        width, height = self.owner.surface.terminal_dimensions()
        try:
            await execution.start(width, height)
            if self.state is state:
                self.owner.surface.publish_terminal(self, terminal_id, execution)
            if self.state is not state:
                raise TerminalSessionRetired("ACP terminal session retired during creation")
            return terminal_id
        except BaseException as error:
            await self.retire(terminal_id)
            if self.state is not state:
                raise TerminalSessionRetired("ACP terminal session retired during creation") from error
            raise

    async def attach(self, binding) -> None:
        if self.owner.surface is not binding:
            return
        for terminal_id, execution in tuple(self.executions.items()):
            binding.publish_terminal(self, terminal_id, execution)

    def owns_projection(self, terminal_id, execution):
        return self.state.owns_projection(self.executions, terminal_id, execution)

    def detach(self) -> None:
        for execution in self.executions.values():
            execution.detach()

    def require(self, terminal_id: str) -> TerminalExecution:
        return self.executions[terminal_id]

    def output(self, terminal_id: str) -> ToolState:
        return self.require(terminal_id).tool_state

    async def wait(self, terminal_id: str):
        return await self.require(terminal_id).wait_for_exit()

    def kill(self, terminal_id: str) -> None:
        self.require(terminal_id).kill()

    async def release(self, terminal_id: str) -> None:
        execution = self.require(terminal_id)
        await join_retirement(asyncio.create_task(self._release(terminal_id, execution)))

    async def _release(self, terminal_id, execution):
        await execution.close()
        # Address membership retires only after the original resource joins.
        self.executions.pop(terminal_id, None)

    async def retire(self, terminal_id) -> None:
        execution = self.executions.get(terminal_id)
        if execution is not None:
            await join_retirement(asyncio.create_task(self._release(terminal_id, execution)))

    async def close(self) -> None:
        self.state = RetiredTerminalControllerState()
        self.detach()
        await join_retirement(asyncio.create_task(self._close()))

    async def _close(self):
        for terminal_id, execution in tuple(self.executions.items()):
            await self._release(terminal_id, execution)
