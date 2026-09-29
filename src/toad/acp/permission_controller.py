"""Actual permission futures belong to the Agent, independently of views."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc
from toad.acp import protocol
from .client_session import ClientRequestOwner, ClientSessionRequest
from toad.answer import Answer
from toad.permission_presentation import PermissionPresentation

PERMISSION_TIMEOUT_SECONDS = 120.0


class PermissionRequest(DeclaredFamily, affix="PermissionRequest"):
    def __init__(self, controller):
        self.controller = controller
        self.future = asyncio.get_running_loop().create_future()
        self._projections = {}
        self.future.add_done_callback(self._completed)

    @property
    def pending(self):
        return not self.future.done()

    @property
    @abstractmethod
    def options(self) -> list[Answer]: ...

    @property
    @abstractmethod
    def presentation(self): ...

    def answer(self, binding, answer):
        if self.pending and self.controller.agent.controller.surface is binding:
            if answer is None or any(option.id == answer.id for option in self.options):
                self.future.set_result(answer)

    def cancel(self):
        if self.pending:
            self.future.set_result(None)

    def watch(self, surface, retire):
        self._projections.setdefault(surface, []).append(retire)

    def detach(self, surface):
        for retire in self._projections.pop(surface, ()):
            retire()

    def _completed(self, future):
        self.controller.requests.discard(self)
        for surface in tuple(self._projections):
            self.detach(surface)

    async def wait(self, timeout):
        try:
            return await asyncio.wait_for(self.future, timeout)
        except TimeoutError:
            return None


class ToolPermissionRequest(PermissionRequest):
    def __init__(self, controller, options, tool_call):
        super().__init__(controller)
        self._options = [Answer(option["name"], option["optionId"], option["kind"]) for option in options]
        self._presentation = PermissionPresentation.from_acp(tool_call)

    @property
    def options(self):
        return self._options

    @property
    def presentation(self):
        return self._presentation


class PermissionController(ClientRequestOwner):
    def __init__(self, agent):
        super().__init__(agent)
        self.requests: set[PermissionRequest] = set()

    @property
    def pending(self):
        return tuple(request for request in self.requests if request.pending)

    def request(self, options, tool_call):
        from .messages import RequestPermission
        request = ToolPermissionRequest(self, options, tool_call)
        self.requests.add(request)
        self.agent.post_message(RequestPermission(request))
        return request

    def present(self, surface):
        from .messages import RequestPermission
        for request in self.pending:
            surface.post_message(RequestPermission(request))

    def detach(self, surface):
        for request in self.pending:
            request.detach(surface)

    def cancel(self):
        for request in self.pending:
            request.cancel()

    @classmethod
    def resolve(cls, agent):
        return agent.permissions

    @jsonrpc.expose("session/request_permission")
    async def request_permission(self, sessionId: str,
                                 options: list[protocol.PermissionOption],
                                 toolCall: protocol.ToolCallUpdatePermissionRequest,
                                 _meta: dict | None = None) -> protocol.RequestPermissionResponse:
        cancelled = {"outcome": {"outcome": "cancelled"}}
        authority = ClientSessionRequest(self.agent, sessionId)
        if authority.retired:
            return cancelled
        visible = self.agent.tools.permission(toolCall)
        request = self.request(options, visible)
        answer = await request.wait(PERMISSION_TIMEOUT_SECONDS)
        if answer is None or authority.retired:
            return cancelled
        return {"outcome": {"optionId": answer.id, "outcome": "selected"}}
