"""A wire channel binds its own fragment flavor before its first page read."""

from toad.widgets.comms_chat import CommsChatView
from toad.widgets.wire_history import WireFragment


async def test_channel_opens_reads_and_sends_with_native_history(workspace):
    me = workspace.project.name
    workspace.thread(me, "source", running=True)
    workspace.comms.messaging.send(me, "#source", "First channel page")
    async with workspace.app(size=(100, 40)) as ui:
        await ui.open_channel("#source", actor=me)
        await ui.until_shows("First channel page")
        chat = ui.textual[0].selected_session.query_one(CommsChatView)
        assert chat.navigation.contents is chat.message_contents
        fragments = chat.message_history.fragments_in_range
        assert fragments and all(isinstance(fragment, WireFragment) for fragment in fragments)
        await ui.write_draft("Reply through the channel reader")
        await ui.press("enter")
        await ui.until(
            lambda: "Reply through the channel reader" in ui.painted(chat.window),
            why="the sent message returning through the channel history",
        )
        assert chat.navigation.contents is chat.message_contents
        assert any(fragment.message.body == "Reply through the channel reader"
                   for fragment in chat.message_history.fragments_in_range)
