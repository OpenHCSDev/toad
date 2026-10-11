"""A painted bounded channel page marks its own members read, never omitted history."""

from unittest.mock import patch


async def test_painted_page_reads_exactly_its_members_and_hidden_expansion_stays_unread(workspace):
    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    project = str(workspace.project)
    hidden = comms.messaging.send_message("bob", "carol", "older hidden DM")
    messages = [comms.messaging.send_message("alice", "#team", f"channel {i}") for i in range(12)]

    def seen():
        return comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())

    # Bound the mounted window too, so automatic edge loading cannot fetch omitted
    # rows and obscure whether the initial page alone was marked.
    with patch("toad.mounted_message_history.INITIAL_HISTORY_PAGE_SIZE", 2), patch(
            "toad.mounted_message_history.HISTORY_WINDOW_SIZE", 2):
        async with workspace.app(size=(120, 40)) as ui:
            owner = ui.selected_tab
            await ui.open_channel("#team", actor=viewer)
            await ui.until(lambda: comms.views.viewer_snapshot(project).channel_unread["#team"] == 10,
                           why="the two painted messages to be marked read")
            assert ui.shows("channel 11") and ui.shows("channel 10") and not ui.shows("channel 9")
            painted = {message.seq for message in messages[-2:]}
            assert seen() == painted
            assert hidden.seq not in seen()
            await ui.select_tab(owner)
            comms.channels.set_channel_any_mode("#team", True)
            comms.channels.update_tags("bob", add=frozenset({"team"}))
            # Expanding a hidden tab's view never manufactures read facts.
            assert comms.views.viewer_snapshot(project).channel_unread["#team"] >= 11
            assert hidden.seq not in seen()
