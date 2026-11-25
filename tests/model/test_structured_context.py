"""Shared structured context, thinking, epistemic certainty, and tool-call rendering."""

from __future__ import annotations

from agent_comms.context_segments.native_messages import TranscriptSegment
from agent_comms.execution.turn_context import UnattributedProvenance
from agent_comms.messaging.messages import InfoKind, Message
from agent_comms.nominal.field_codec import ToolCallId
from agent_comms.pi_payloads import (
    AssistantMessage,
    ReportedParts,
    TextContent,
    ThinkingContent,
    ToolCallContent,
)
from agent_comms.transcript.transcript_events import AgentTextTranscript, ThinkingTranscript

from toad.client.agent_activity import AgentActivityPresentation
from toad.client.fragments import OnlyPart
from toad.client.line_blocks import MarkdownBody, MutedRole, Summary, ThinkingRole
from toad.client.structured_context import (
    AnswerPart,
    LiveContextPart,
    ThinkingPart,
    ToolCallPart,
    parse_context_sections,
    parse_structured_text,
)
from toad.client.transcript_fragments import FragmentLineConsumer
from toad.core.context_inspection import NativeMessageNode, StructuredSectionNode
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle, MessageRow


def test_parse_structured_text_separates_thinking_ctx_tool_call_and_answer():
    raw = (
        "<think>\n"
        "Certainty:\n"
        "- DEDUCED: The commit hash is 8a3e7bbc. Basis: git rev-parse --short HEAD returned 8a3e7bbc\n"
        "- ASSUMED: The repo is clean\n"
        "Confidence: 0.94\n"
        "</think>\n"
        "<ctx>\n"
        "[[CTX_TURN 1 role=user]]\n"
        "Check git HEAD\n"
        "[[CTX_TURN 2 role=assistant]]\n"
        "Ran git rev-parse\n"
        "[context: ~1995/26624 tokens]\n"
        "</ctx>\n"
        "<tool_call><function=bash><parameter=command>ls logs</parameter></function></tool_call>\n"
        "8a3e7bbc"
    )
    parts = parse_structured_text(raw)
    assert [type(part) for part in parts] == [
        ThinkingPart,
        LiveContextPart,
        ToolCallPart,
        AnswerPart,
    ]
    thinking, live_ctx, tool_call, answer = parts
    assert isinstance(thinking, ThinkingPart)
    assert len(thinking.claims) == 2
    assert thinking.claims[0].status == "DEDUCED"
    assert thinking.claims[0].basis == "git rev-parse --short HEAD returned 8a3e7bbc"
    assert thinking.confidence == "0.94"
    assert "1 deduced, 1 assumed" in thinking.summary_title
    assert "Confidence: 0.94" in thinking.summary_title

    assert isinstance(live_ctx, LiveContextPart)
    assert len(live_ctx.sections) == 2
    assert live_ctx.sections[0].heading == "Turn 1 · user"
    assert live_ctx.sections[1].heading == "Turn 2 · assistant"
    assert "~1995/26624 tokens" in live_ctx.label

    assert isinstance(tool_call, ToolCallPart)
    assert tool_call.name == "bash"
    assert tool_call.arguments_text == "ls logs"
    assert isinstance(answer, AnswerPart)
    assert answer.text == "8a3e7bbc"


def test_parse_structured_text_handles_unclosed_streaming_think():
    parts = parse_structured_text("<think>Checking whether the file exists")
    assert len(parts) == 1
    thinking = parts[0]
    assert isinstance(thinking, ThinkingPart)
    assert thinking.streaming is True
    assert thinking.summary_title.startswith("Thinking…")
    blocks = thinking.line_blocks()
    assert isinstance(blocks[0], Summary)
    assert blocks[0].spans[0].role is ThinkingRole
    assert all("<think>" not in getattr(block, "text", "") for block in blocks)


def test_plain_text_passes_through_without_extra_wrapping():
    parts = parse_structured_text("Ordinary reply with 2 < 3 and no tags.")
    assert parts == (AnswerPart("Ordinary reply with 2 < 3 and no tags."),)
    assert parse_context_sections("Ordinary unstructured note.") == ()


def test_markdown_code_and_unclosed_prose_tags_do_not_swallow_messages():
    # Exact pattern from #model 6199 that split mid-backtick and ate the rest of the message.
    prose_with_code = (
        "Stage 0/1: CLM `<ctx>` + git/Zarr lossless `.live_ctx/originals/`, "
        "plus `train_loop.py` and `<think>` examples."
    )
    assert parse_structured_text(prose_with_code) == (AnswerPart(prose_with_code),)
    assert parse_structured_text(prose_with_code, allow_unclosed=False) == (AnswerPart(prose_with_code),)

    fenced = "Example:\n```xml\n<ctx>not live</ctx>\n```\nAfter fence."
    assert parse_structured_text(fenced) == (AnswerPart(fenced),)

    # Unclosed tag in a completed bus message stays literal prose instead of becoming streaming.
    unclosed = "Discussing <ctx> without backticks and rest of message."
    assert parse_structured_text(unclosed, allow_unclosed=False) == (AnswerPart(unclosed),)
    row = MessageRow(Message(sender="clm-live", target="#model", body=prose_with_code, type=InfoKind), reader="tristan")
    for style in (IrcMessageStyle(), MarkdownMessageStyle()):
        blocks = style.body(row, prose_with_code)
        assert not any(isinstance(block, Summary) for block in blocks)
        assert len(blocks) == 1


def test_transcript_and_wire_message_render_structured_blocks_without_raw_xml():
    raw = "<think>Certainty:\n- DEDUCED: ok. Basis: ran test</think>\nFinal answer."
    consumer = FragmentLineConsumer(part=OnlyPart())
    consumer.project_value(AgentTextTranscript(raw, position=1, timestamp=0.0))
    summary_blocks = [block for block in consumer.blocks if isinstance(block, Summary)]
    assert any("Thinking · 1 deduced" in block.spans[0].text for block in summary_blocks)
    assert any(isinstance(block, MarkdownBody) and block.text == "Final answer." for block in consumer.blocks)
    assert all("<think>" not in getattr(block, "text", "") for block in consumer.blocks)

    thinking_blocks = AgentActivityPresentation.thinking(
        "Certainty:\n- DEDUCED: grounded. Basis: live stdout\nConfidence: 0.99"
    )
    assert isinstance(thinking_blocks[0], Summary)
    assert "1 deduced" in thinking_blocks[0].spans[0].text
    assert "Confidence: 0.99" in thinking_blocks[0].spans[0].text

    row = MessageRow(Message(sender="clm-live", target="#model", body=raw, type=InfoKind), reader="tristan")
    for style in (IrcMessageStyle(), MarkdownMessageStyle()):
        blocks = style.body(row, raw)
        assert any(isinstance(block, Summary) and block.spans[0].role is ThinkingRole for block in blocks)
        assert all("<think>" not in getattr(block, "text", "") for block in blocks)


def test_native_message_node_expands_thinking_ctx_and_tool_calls_while_keeping_public_text():
    thought = ThinkingContent(thinking="Certainty:\n- DEDUCED: answer is 42. Basis: measured\nConfidence: 0.98")
    text = TextContent(text="<ctx>\n=== PROJECT CONTEXT ===\nRepo: personal-model\n</ctx>\n42")
    call = ToolCallContent(id=ToolCallId("call-1"), name="bash", arguments={"command": "echo 42"})
    message = AssistantMessage(content=ReportedParts((thought, text, call)))
    segment = TranscriptSegment(
        provenance=(UnattributedProvenance(),), sha256="", tokens=0, utf8_bytes=0, messages=()
    )
    node = NativeMessageNode("native/0", segment, None, message, 0)

    children = node.children()
    assert len(children) == 4
    assert all(isinstance(child, StructuredSectionNode) for child in children)
    assert isinstance(children[0].part, ThinkingPart)
    assert isinstance(children[1].part, LiveContextPart)
    assert isinstance(children[2].part, AnswerPart)
    assert isinstance(children[3].part, ToolCallPart)
    # Thinking claims expand as children too; LiveContext expands sections
    assert len(children[0].children()) == 1
    assert len(children[1].children()) == 1
    assert children[1].children()[0].label.startswith("Project Context")
    # Public search text still excludes private thinking
    assert "Confidence: 0.98" not in node.public_text()
    assert "echo 42" in node.public_text()
    assert "Certainty:" in node.detail()
    assert "Tool call · bash" in node.detail()
    # Context blocks render in MutedRole
    ctx_blocks = children[1].part.line_blocks()
    assert isinstance(ctx_blocks[0], Summary)
    assert ctx_blocks[0].spans[0].role is MutedRole
