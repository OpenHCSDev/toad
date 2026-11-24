"""Actual permission futures belong to the Agent, independently of views."""
from __future__ import annotations

import asyncio
from abc import abstractmethod

from acp import schema as protocol
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec

from toad.acp.client_session import ClientRequestOwner, ClientSessionRequest
from toad.answer import Answer
from toad.client.interactive_dialog import DialogCancelled, DialogOutcome, DialogSpec
from toad.core.events import RequestPermission
from toad.permission_presentation import DialogPermissionPresentation, PermissionPresentation

PERMISSION_TIMEOUT_SECONDS = 120.0


class PermissionRequest(DeclaredFamily, affix="PermissionRequest"):
    def __init__(self, controller, presentation: PermissionPresentation):
        self.controller = controller
        self._presentation = presentation
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
    def presentation(self) -> PermissionPresentation:
        return self._presentation

    def answer(self, binding, answer):
        if self.owns_projection(binding, binding.target):
            if answer is None or any(option.id == answer.id for option in self.options):
                self.future.set_result(answer)

    def cancel(self):
        if self.pending:
            self.future.set_result(None)

    def current_on(self, binding, surface):
        """The original controller and surface own this attachment."""
        return (self.controller.agent.controller.surface is binding
                and binding.owns(surface))

    def owns_projection(self, binding, surface):
        return self.pending and self.current_on(binding, surface) and binding in self._projections

    async def present(self, surface):
        """Acquire once before asynchronous frontend work; retain its callbacks."""
        binding = self.controller.agent.controller.surface
        if not self.pending or not self.current_on(binding, surface) or binding in self._projections:
            return
        self._projections[binding] = []
        try:
            binding.permission_changed(surface)
            await binding.present_permission(self, surface)
        except BaseException:
            self._retire_projection(binding)
            raise
        finally:
            if self.current_on(binding, surface):
                binding.permission_changed(surface)

    def watch(self, binding, retire):
        surface = binding.target
        if not self.owns_projection(binding, surface):
            retire()
            return False
        self._projections[binding].append(retire)
        return True

    def detach(self, surface):
        for binding in tuple(self._projections):
            if binding.owns(surface):
                self._retire_projection(binding)

    def _retire_projection(self, binding):
        for retire in self._projections.pop(binding, ()):
            retire()

    def _completed(self, future):
        self.controller.requests.discard(self)
        for binding in tuple(self._projections):
            self._retire_projection(binding)

    async def wait(self, timeout):
        try:
            return await asyncio.wait_for(self.future, timeout)
        except TimeoutError:
            return None


class ToolPermissionRequest(PermissionRequest):
    def __init__(self, controller, options, tool_call):
        super().__init__(controller, PermissionPresentation.from_acp(tool_call))
        self._options = [Answer(option.name, option.option_id, option.kind) for option in options]

    @property
    def options(self):
        return self._options


class ElicitationRequest(PermissionRequest):
    """A structured dialog / ACP `elicitation/create` request sharing the permission lifecycle."""

    def __init__(self, controller, spec: DialogSpec):
        super().__init__(controller, DialogPermissionPresentation(spec.title or spec.message, spec))
        self.spec = spec

    @property
    def options(self) -> list[Answer]:
        return []

    def resolve(self, binding, outcome: DialogOutcome) -> None:
        if self.owns_projection(binding, binding.target) and self.pending:
            self.future.set_result(outcome)


class PermissionController(ClientRequestOwner):
    def __init__(self, agent):
        super().__init__(agent)
        self.requests: set[PermissionRequest] = set()

    @property
    def pending(self):
        return tuple(request for request in self.requests if request.pending)

    def request(self, options, tool_call):
        request = ToolPermissionRequest(self, options, tool_call)
        self.requests.add(request)
        self.agent.events.publish(RequestPermission())
        return request

    def request_dialog(self, spec: DialogSpec) -> ElicitationRequest:
        request = ElicitationRequest(self, spec)
        self.requests.add(request)
        self.agent.events.publish(RequestPermission())
        return request

    def present(self):
        if self.pending:
            self.agent.events.publish(RequestPermission())

    def detach(self, surface):
        for request in self.pending:
            request.detach(surface)

    def cancel(self):
        for request in self.pending:
            request.cancel()

    async def request_permission(self, sessionId: str,
                                 options: list[protocol.PermissionOption],
                                 toolCall: protocol.ToolCallUpdate,
                                 _meta: dict | None = None) -> protocol.RequestPermissionResponse:
        cancelled = protocol.RequestPermissionResponse(outcome=protocol.DeniedOutcome(outcome="cancelled"))
        authority = ClientSessionRequest(self.agent, FieldCodec.decode(AcpSessionId, sessionId))
        if authority.retired:
            return cancelled
        visible = self.agent.tools.permission(toolCall)
        request = self.request(options, visible)
        answer = await request.wait(PERMISSION_TIMEOUT_SECONDS)
        if answer is None or authority.retired:
            return cancelled
        return protocol.RequestPermissionResponse(outcome=protocol.AllowedOutcome(option_id=answer.id, outcome="selected"))

    async def request_elicitation(
        self,
        session_id: str,
        message: str,
        requested_schema: protocol.ElicitationSchema,
    ) -> protocol.CreateElicitationResponse:
        cancelled = DialogCancelled().to_elicitation_response()
        authority = ClientSessionRequest(self.agent, FieldCodec.decode(AcpSessionId, session_id))
        if authority.retired:
            return cancelled
        spec = DialogSpec.from_elicitation(message, requested_schema)
        request = self.request_dialog(spec)
        outcome = await request.wait(PERMISSION_TIMEOUT_SECONDS)
        if outcome is None or authority.retired:
            return cancelled
        return outcome.to_elicitation_response()
