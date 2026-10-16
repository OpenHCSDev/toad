"""Nominal terminal capability shared by operational Agent controllers."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .terminal_controller import TerminalController, TerminalSessionRetired
from .client_session import ClientRequestOwner
from toad import jsonrpc
from acp import schema as protocol
from toad.terminal_execution import Command

if TYPE_CHECKING:
    from toad.surface_binding import SurfaceBinding


class OperationalTerminalOwner(ClientRequestOwner, ABC):
    surface: "SurfaceBinding"

    def __init__(self, agent) -> None:
        super().__init__(agent)
        self.terminals = TerminalController(self)

    @abstractmethod
    def start_operation(self, operation): ...

    def start_terminal_presentation(self, target):
        if self.surface.owns(target):
            self.start_operation(self.terminals.attach(self.surface))

    def owns_terminal_projection(self, binding, projection):
        if self.surface is not binding or self.terminals is not projection.controller:
            return False
        return self.terminals.owns_projection(projection.terminal_id, projection.execution)

    def replace_terminal_session(self):
        previous = self.terminals
        self.terminals = TerminalController(self)
        if previous.executions:
            self.start_operation(previous.close())
        self.start_terminal_presentation(self.surface.target)


    @classmethod
    def resolve(cls, agent):
        return agent.controller

    @jsonrpc.expose("terminal/create")
    async def terminal_create(self, sessionId: str, command: str,
                              _meta: dict | None = None, args: list[str] | None = None,
                              cwd: str | None = None, env: list[protocol.EnvVariable] | None = None,
                              outputByteLimit: int | None = None) -> protocol.CreateTerminalResponse:
        authority = self.session_request(sessionId)
        terminals = self.terminals
        terminal_env = {variable.name: variable.value for variable in env} if env else {}
        try:
            terminal_id = await terminals.create(
                Command.for_argv(command, args or [], env=terminal_env,
                                 cwd=cwd or str(self.agent.project_root_path)),
                outputByteLimit)
        except TerminalSessionRetired as error:
            raise jsonrpc.InvalidParams(str(error)) from error
        if authority.current and self.terminals is terminals:
            return protocol.CreateTerminalResponse(terminal_id=terminal_id)
        await terminals.retire(terminal_id)
        authority.require()
        raise jsonrpc.InvalidParams("ACP terminal owner was replaced during creation")

    @jsonrpc.expose("terminal/kill")
    def terminal_kill(self, sessionId: str, terminalId: str, _meta: dict | None = None) -> protocol.KillTerminalResponse:
        self.session_request(sessionId)
        self.terminals.kill(terminalId)
        return protocol.KillTerminalResponse()

    @jsonrpc.expose("terminal/output")
    async def terminal_output(self, sessionId: str, terminalId: str, _meta: dict | None = None) -> protocol.TerminalOutputResponse:
        self.session_request(sessionId)
        return self.terminals.output(terminalId).response()

    @jsonrpc.expose("terminal/release")
    async def terminal_release(self, sessionId: str, terminalId: str, _meta: dict | None = None) -> protocol.ReleaseTerminalResponse:
        self.session_request(sessionId)
        await self.terminals.release(terminalId)
        return protocol.ReleaseTerminalResponse()

    @jsonrpc.expose("terminal/wait_for_exit")
    async def terminal_wait_for_exit(self, sessionId: str, terminalId: str, _meta: dict | None = None) -> protocol.WaitForTerminalExitResponse:
        authority = self.session_request(sessionId)
        terminals = self.terminals
        completion = await terminals.wait(terminalId)
        authority.require()
        if self.terminals is not terminals:
            raise jsonrpc.InvalidParams("ACP terminal owner was replaced while awaiting exit")
        return completion.wait_response()
