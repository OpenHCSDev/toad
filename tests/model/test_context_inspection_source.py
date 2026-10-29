"""What a native message shows."""

import json

from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.pi_payloads import AssistantMessage, TextContent, ToolCallContent
from toad.core.context_inspection import NativeMessageNode


def test_native_message_text_includes_its_tool_calls():
    call = ToolCallContent(id="call-1", name="read", arguments={"path": "notes.md"})
    message = AssistantMessage(content=(TextContent(text="Reading the notes."), call))
    node = NativeMessageNode("native/0", None, None, message, 0)

    said, called = node.public_text().split("\n", 1)
    assert said == "Reading the notes."
    shown = json.loads(called)
    assert shown == FieldCodec.encode(call)
    assert (shown["name"], shown["arguments"]) == ("read", {"path": "notes.md"})
