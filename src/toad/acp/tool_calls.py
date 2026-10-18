"""One session owns SDK tool-call assembly and the session that supplied it."""
from dataclasses import dataclass, replace

from acp.schema import ToolCall, ToolCallStart, ToolCallUpdate
from agent_comms.transcript_sources import AssignedSourceIdentity
from toad.core import events
from toad.acp.client_session import ClientSessionRequest
from toad.acp.status import ToolCallStatus


@dataclass(frozen=True)
class SessionToolCall:
    call: ToolCall
    request: ClientSessionRequest
    scope: AssignedSourceIdentity | None

    def update(self, value: ToolCallUpdate):
        changes = {name: getattr(value, name) for name in value.model_fields_set
                   if name in ToolCall.model_fields and getattr(value, name) is not None}
        return replace(self, call=self.call.model_copy(update=changes, deep=True))

    def accepts(self, event, scope):
        return (self.request.current and self.call is event.tool_call.call
                and event.in_native_source(scope))


class SessionToolCalls:
    def __init__(self, agent):
        self.agent = agent
        self.calls: dict[str, SessionToolCall] = {}

    def reset(self):
        self.calls.clear()

    @property
    def scope(self):
        coordination = self.agent.coordination
        return None if coordination is None else coordination.thread.recorded_or(
            lambda recorded: AssignedSourceIdentity(coordination.wire_root, recorded),
            lambda: None,
        )

    def capture(self, call):
        return SessionToolCall(call, ClientSessionRequest(self.agent, self.agent.session_id), self.scope)

    def presentation(self, event):
        current = self.calls.get(event.tool_call.call.tool_call_id)
        return current if current is not None and current.accepts(event, self.scope) else None

    def publish(self, current):
        self.agent.events.publish(events.ToolCall(ToolCallStatus.from_acp(current.call), current.scope))

    def begin(self, value: ToolCallStart):
        # The boundary validated inherited SDK fields already. Keep that SDK
        # snapshot with the exact existing session request, never inside it.
        current = self.capture(ToolCall.model_construct(**{
            name: getattr(value, name) for name in ToolCall.model_fields
        }))
        self.calls[value.tool_call_id] = current
        self.publish(current)

    def merge(self, value: ToolCallUpdate):
        tool_id = value.tool_call_id
        current = self.calls.get(tool_id)
        if current is None or current.request.retired:
            current = self.capture(ToolCall(tool_call_id=tool_id, title='Tool call'))
        current = current.update(value)
        self.calls[tool_id] = current
        return current

    def update(self, value):
        self.publish(self.merge(value))

    def permission(self, value):
        return self.merge(value).call
