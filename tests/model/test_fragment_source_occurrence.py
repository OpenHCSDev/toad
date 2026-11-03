"""A fragment's key names its source occurrence: one Pi reply's thinking parts, which share the
reply's position, are different messages to the reader, the details toggle and page lookup."""

from agent_comms.transcript_events import AssistantTranscript, ThinkingTranscript

from toad.widgets.transcript_fragments import RenderBudget, transcript_fragments


def fragments(*events):
    return transcript_fragments(events, resolve_sent=lambda reports: {})


def test_thinking_parts_of_one_reply_have_distinct_keys():
    reply = 7
    built = fragments(
        ThinkingTranscript("First thought", position=reply, timestamp=0.0),
        AssistantTranscript("Calling a tool", position=reply, timestamp=0.0),
        ThinkingTranscript("Second thought", position=reply, timestamp=0.0),
    )
    thoughts = [fragment for fragment in built if isinstance(fragment.events[0], ThinkingTranscript)]
    assert [fragment.events[0].text for fragment in thoughts] == ["First thought", "Second thought"]
    assert thoughts[0].key != thoughts[1].key
    assert len({fragment.key for fragment in built}) == len(built)


def test_every_part_of_one_long_event_shares_its_source_identity():
    paragraphs = "\n\n".join(f"Paragraph {index} " + "word " * 40 for index in range(12))
    reply = 3
    built = fragments(
        ThinkingTranscript("Short", position=reply, timestamp=0.0),
        ThinkingTranscript(paragraphs, position=reply, timestamp=0.0),
    )
    long_parts = built[1:]
    assert len(long_parts) > 1, "the long thought must split under the render budget"
    assert len(paragraphs) > RenderBudget().characters
    assert {part.source_identity for part in long_parts} == {long_parts[0].source_identity}
    assert long_parts[0].source_identity != built[0].source_identity
    assert len({fragment.key for fragment in built}) == len(built)
