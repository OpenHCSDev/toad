"""One session owns SDK tool-call assembly for updates and permission admission."""
from acp.schema import ToolCall
from toad.core import events
from toad.acp.status import ToolCallStatus, PendingToolCallStatus




class SessionToolCalls:
    def __init__(self, agent):
        self.agent = agent
        self.calls: dict[str, ToolCall] = {}

    def reset(self):
        self.calls.clear()

    def begin(self, value):
        current = ToolCall(**{name: getattr(value, name) for name in ToolCall.model_fields})
        self.calls[value.tool_call_id] = current
        self.agent.events.publish(events.ToolCall(ToolCallStatus.from_acp(current)))

    def merge(self, value):
        tool_id = value.tool_call_id
        current = self.calls.get(tool_id, ToolCall(tool_call_id=tool_id, title='Tool call'))
        changes = {name: getattr(value, name) for name in value.model_fields_set
                   if name in ToolCall.model_fields and getattr(value, name) is not None}
        current = current.model_copy(update=changes, deep=True)
        self.calls[tool_id] = current
        return current

    def update(self, value):
        current = self.merge(value)
        self.agent.events.publish(events.ToolCall(ToolCallStatus.from_acp(current)))

    def permission(self, value):
        return self.merge(value)
