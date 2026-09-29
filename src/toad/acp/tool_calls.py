"""One session owns tool-call assembly for updates and permission admission."""
from copy import deepcopy
from toad.acp import messages


class SessionToolCalls:
    def __init__(self, agent):
        self.agent = agent
        self.calls = {}

    def reset(self):
        self.calls.clear()

    def begin(self, value):
        current = deepcopy(value)
        self.calls[value['toolCallId']] = current
        self.agent.post_message(messages.ToolCall(deepcopy(current)))

    def merge(self, value):
        tool_id = value['toolCallId']
        current = self.calls.setdefault(tool_id, {
            'sessionUpdate': 'tool_call', 'toolCallId': tool_id, 'title': 'Tool call'})
        current.update((key, deepcopy(item)) for key, item in value.items()
                       if item is not None and key != 'sessionUpdate')
        return deepcopy(current)

    def update(self, value):
        known = value['toolCallId'] in self.calls
        current = self.merge(value)
        if known:
            self.agent.post_message(messages.ToolCallUpdate(current, value))
        else:
            self.agent.post_message(messages.ToolCall(current))

    def permission(self, value):
        current = self.merge(value)
        current.pop('sessionUpdate', None)
        return current
