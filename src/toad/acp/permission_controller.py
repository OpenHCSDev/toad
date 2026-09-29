"""Actual permission futures belong to the Agent, independently of views."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from toad.answer import Answer


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
    def tool_call(self): ...

    def answer(self, surface, answer):
        if self.pending and self.controller.agent.controller.surface.owns(surface):
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
        self._tool_call = tool_call

    @property
    def options(self):
        return self._options

    @property
    def tool_call(self):
        return self._tool_call


class PermissionController:
    def __init__(self, agent):
        self.agent = agent
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
