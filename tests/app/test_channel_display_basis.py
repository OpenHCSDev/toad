"""A channel marks read exactly the messages whose text it showed, never the history it left out."""
import pytest

from agent_comms.read_basis import ChannelConversation, NamedViewer
from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.unread import ExactUnread
from support.painted_app import PaintedApp


@pytest.mark.parametrize("height", [39, 40, 41, 43, 47])
async def test_shown_messages_are_read_exactly_and_hidden_expansion_stays_unread(workspace, height):
    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    project = Checkout(workspace.project)
    hidden = comms.messaging.send("bob", "carol", "older hidden DM").message
    # Every line of a message names it, so a message whose text is partly on screen is recognisable.
    messages = [comms.messaging.send("alice", "#team", "\n".join(f"channel {i:02d} line" for _ in range(12))).message
                for i in range(12)]

    ledger = comms.bus.reads
    snapshot = comms.registry.snapshot()
    channel = ChannelConversation("#team")

    async with workspace.app(size=(120, height), application=PaintedApp) as ui:
        owner = ui.selected_tab
        await ui.open_channel("#team", actor=viewer)
        await ui.until_shows("channel 11 line")

        def shown():
            app, _pilot = ui.textual
            return {message.seq for i, message in enumerate(messages) if app.has_shown(f"channel {i:02d} line")}

        await ui.until(lambda: all(
            (message.seq in ledger.cursor(viewer, snapshot).for_conversation(channel))
            == (message.seq in shown()) for message in messages
        ), why="the shown messages to be marked read")
        # Cold loading can paint an earlier page before following the tail.
        # Those reads remain valid after it leaves the screen. The unread
        # messages are exactly those absent from every accepted frame.
        assert 0 < len(shown()) < len(messages)
        assert comms.views.viewer_snapshot(project).channel_unread["#team"] == ExactUnread(
            count=len(messages) - len(shown()))
        assert hidden.seq not in ledger.cursor(viewer, snapshot).for_conversation(
            ledger.conversation(hidden, snapshot))
        shown_before_leaving = shown()
        await ui.select_tab(owner)
        comms.channels.set_channel_any_mode("#team", True)
        comms.channels.update_tags("bob", add=frozenset({"team"}))
        # Expanding a hidden tab's view never manufactures read facts.
        # Tag changes also publish membership messages. Acquire the expanded
        # source without acknowledging it; every row not actually shown stays
        # unread, including those new announcements and the older hidden DM.
        expanded = comms.views.presentation.channel_page("#team", viewer=NamedViewer(viewer))
        current = comms.registry.snapshot()
        cursor = ledger.cursor(viewer, current)
        for message in expanded.messages:
            assert (message.seq in cursor.for_conversation(ledger.conversation(message, current))) == (
                message.seq in shown_before_leaving)
        assert comms.views.viewer_snapshot(project).channel_unread["#team"] == ExactUnread(
            count=len({message.seq for message in expanded.messages} - shown_before_leaving))
        assert hidden.seq not in ledger.cursor(viewer, snapshot).for_conversation(
            ledger.conversation(hidden, snapshot))
