"""A channel marks read exactly the messages whose text it showed, never the history it left out."""
from agent_comms.repo import Checkout


async def test_shown_messages_are_read_exactly_and_hidden_expansion_stays_unread(workspace):
    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    project = str(workspace.project)
    hidden = comms.messaging.send_message("bob", "carol", "older hidden DM")
    # Every line of a message names it, so a message whose text is partly on screen is recognisable.
    messages = [comms.messaging.send_message("alice", "#team", "\n".join(f"channel {i:02d} line" for _ in range(12)))
                for i in range(12)]

    def seen():
        return comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())

    async with workspace.app(size=(120, 40)) as ui:
        owner = ui.selected_tab
        await ui.open_channel("#team", actor=viewer)
        await ui.until_shows("channel 11 line")

        def shown():
            return {message.seq for i, message in enumerate(messages) if ui.shows(f"channel {i:02d} line")}

        await ui.until(lambda: seen() == shown(), why="the shown messages to be marked read")
        # Earlier messages were read from Core for scrolling, but never shown.
        assert 0 < len(shown()) < len(messages) and not ui.shows("channel 00 line")
        assert comms.views.viewer_snapshot(Checkout(project)).channel_unread["#team"] == len(messages) - len(shown())
        assert hidden.seq not in seen()
        await ui.select_tab(owner)
        comms.channels.set_channel_any_mode("#team", True)
        comms.channels.update_tags("bob", add=frozenset({"team"}))
        # Expanding a hidden tab's view never manufactures read facts.
        assert comms.views.viewer_snapshot(Checkout(project)).channel_unread["#team"] >= len(messages) - len(shown()) + 1
        assert hidden.seq not in seen()
