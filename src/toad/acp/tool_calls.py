"""One session owns SDK tool-call assembly for updates and permission admission."""
from acp.schema import ToolCall, ToolCallStart, ToolCallUpdate
from toad.core import events
from toad.acp.status import ToolCallStatus, PendingToolCallStatus




class SessionToolCalls:
    def __init__(self, agent):
        self.agent = agent
        self.calls: dict[str, ToolCall] = {}

    def reset(self):
        self.calls.clear()

    @property
    def scope(self):
        coordination = self.agent.coordination
        return None if coordination is None else coordination.source_identity

    def owns_presentation(self, event):
        """Only this session's still-current SDK snapshot can publish native paint."""
        call = event.tool_call.call
        if self.calls.get(call.tool_call_id) is not call:
            return False
        return event.in_native_source(self.scope)

    def publish(self, current):
        self.agent.events.publish(events.ToolCall(ToolCallStatus.from_acp(current), self.scope))

    def begin(self, value: ToolCallStart):
        # The admitted SDK notification already validated every inherited
        # ToolCall field. Assembly owns the canonical snapshot (without the
        # wire discriminator), not a second parse of those same values.
        current = ToolCall.model_construct(**{
            name: getattr(value, name) for name in ToolCall.model_fields
        })
        self.calls[value.tool_call_id] = current
        self.publish(current)

    def merge(self, value: ToolCallUpdate):
        tool_id = value.tool_call_id
        current = self.calls.get(tool_id)
        if current is None:
            current = ToolCall(tool_call_id=tool_id, title='Tool call')
        changes = {name: getattr(value, name) for name in value.model_fields_set
                   if name in ToolCall.model_fields and getattr(value, name) is not None}
        current = current.model_copy(update=changes, deep=True)
        self.calls[tool_id] = current
        return current

    def update(self, value):
        current = self.merge(value)
        self.publish(current)

    def permission(self, value):
        return self.merge(value)
