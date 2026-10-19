"""When a context read from the running agent still describes a thread, and what a native message shows."""

import json
from dataclasses import replace

from agent_comms.field_codec import FieldCodec
from agent_comms.pi_payloads import AssistantMessage, TextContent, ToolCallContent
from agent_comms.session_revision import SessionRevision
from agent_comms.registration import Registration
from toad.core.context_inspection import ContextInspection, HoldingInspection, NativeMessageNode


def inspect(thread):
    return ContextInspection(thread, (), SessionRevision.observe(thread.session_file), service=None)


def test_held_native_context_is_read_again_only_when_its_launch_or_session_changes(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text("{}\n")
    thread = Registration(tmp_path / "registry.json").new_thread(
        "owner", frozenset(), str(tmp_path), session_file=str(session), model="model-a", created_at=1.0)
    held = HoldingInspection(inspect(thread), revision=1)

    assert not held.needs_native(inspect(replace(thread, title="A new title")), False)
    assert held.needs_native(inspect(replace(thread, model="model-b")), False)
    assert held.needs_native(inspect(replace(thread, created_at=2.0)), False)
    session.write_text("{}\n{}\n")
    assert held.needs_native(inspect(thread), False)


def test_native_message_text_includes_its_tool_calls():
    call = ToolCallContent(id="call-1", name="read", arguments={"path": "notes.md"})
    message = AssistantMessage(content=(TextContent(text="Reading the notes."), call))
    node = NativeMessageNode("native/0", None, None, message, 0)

    said, called = node.public_text().split("\n", 1)
    assert said == "Reading the notes."
    shown = json.loads(called)
    assert shown == FieldCodec.encode(call)
    assert (shown["name"], shown["arguments"]) == ("read", {"path": "notes.md"})
