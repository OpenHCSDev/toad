"""A mounted any-mode channel reveals older messages entering its scope."""


async def test_mounted_any_mode_channel_reveals_older_messages_entering_its_scope(workspace):
    for name, tags in (("alice", ("team",)), ("bob", ()), ("carol", ()), ("dave", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    comms.messaging.send("carol", "dave", "older newly visible DM")
    comms.messaging.send("alice", "#team", "current channel message")
    comms.channels.set_channel_any_mode("#team", True)
    assert [m.body for m in comms.views.channel_display_page("#team", worktree=str(workspace.project)).messages] == [
        "current channel message"]

    async with workspace.app(size=(100, 30)) as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("current channel message")
        assert not ui.shows("older newly visible DM")

        comms.channels.update_tags("carol", add=frozenset({"team"}))
        await ui.until_shows("older newly visible DM")
        lines = ui.visible_lines()
        assert (next(i for i, l in enumerate(lines) if "older newly visible DM" in l)
                < next(i for i, l in enumerate(lines) if "current channel message" in l))
