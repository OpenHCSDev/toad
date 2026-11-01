"""A channel marks read exactly the messages whose text it showed, never the history it left out."""
from agent_comms.read_basis import ChannelConversation
from agent_comms.repo import Checkout
from agent_comms.ui_model.unread import ExactUnread


async def test_shown_messages_are_read_exactly_and_hidden_expansion_stays_unread(workspace):
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

    async with workspace.app(size=(120, 40)) as ui:
        owner = ui.selected_tab
        await ui.open_channel("#team", actor=viewer)
        await ui.until_shows("channel 11 line")

        def shown():
            return {message.seq for i, message in enumerate(messages) if ui.shows(f"channel {i:02d} line")}

        await ui.until(lambda: all(
            (message.seq in ledger.cursor(viewer, snapshot).for_conversation(channel))
            == (message.seq in shown()) for message in messages
        ), why="the shown messages to be marked read")
        # Earlier messages were read from Core for scrolling, but never shown.
        assert 0 < len(shown()) < len(messages) and not ui.shows("channel 00 line")
        assert comms.views.viewer_snapshot(project).channel_unread["#team"] == ExactUnread(
            count=len(messages) - len(shown()))
        assert hidden.seq not in ledger.cursor(viewer, snapshot).for_conversation(
            ledger.conversation(hidden, snapshot))
        await ui.select_tab(owner)
        comms.channels.set_channel_any_mode("#team", True)
        comms.channels.update_tags("bob", add=frozenset({"team"}))
        # Expanding a hidden tab's view never manufactures read facts.
        assert comms.views.viewer_snapshot(project).channel_unread["#team"] == ExactUnread(
            count=len(messages) - len(shown()) + 1)
        assert hidden.seq not in ledger.cursor(viewer, snapshot).for_conversation(
            ledger.conversation(hidden, snapshot))
