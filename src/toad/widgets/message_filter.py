"""Presentation-only routing classification for native live and saved blocks."""

from agent_comms import TranscriptEvent


def is_routed_event(event: TranscriptEvent) -> bool:
    routing = event.routing
    if routing is None:
        return False
    if event.kind == "user":
        return bool(routing.requests)
    return event.kind in {"assistant", "notice", "sent"} and routing.reply is not None


def keep_live_block(widget) -> bool:
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.incoming_message import IncomingMessage
    from toad.widgets.transcript_history import TranscriptHistory

    # Keep the pager itself; its saved semantic fragments are classified
    # separately. Nested pagers within an already-routed body stay untouched.
    return (isinstance(widget, (IncomingMessage, TranscriptHistory))
            or isinstance(widget, AgentResponse) and widget.route is not None)
