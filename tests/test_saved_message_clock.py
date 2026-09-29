"""Saved dividers preserve source time, including an explicitly unknown time."""
import time

from agent_comms.transcript_events import AssistantTranscript, UserTranscript
from toad.widgets.message_divider import MessageClock, MessageDivider
from toad.widgets.transcript_history import transcript_blocks


def test_saved_user_and_agent_use_original_clock():
    timestamp = 1234567890.125
    user, agent = transcript_blocks((
        UserTranscript("saved user", timestamp=timestamp),
        AssistantTranscript("saved agent", timestamp=timestamp),
    ))
    expected = time.strftime("%H:%M:%S", time.localtime(timestamp))
    assert user.clock.display()[0] == expected
    assert agent._prefix[0].clock == expected


def test_missing_saved_time_never_becomes_receipt_time():
    user, agent = transcript_blocks((UserTranscript("user"), AssistantTranscript("agent")))
    assert user.clock.display() == ("time unknown", None)
    assert agent._prefix[0].clock == "time unknown"
    assert MessageDivider("Saved", clock=MessageClock.recorded(None)).clock == "time unknown"
