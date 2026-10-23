"""A channel has one tab however many sessions open it; what that tab does for the second session.

One tab per channel is deliberate (channel tabs are keyed by wire and channel, not
by the session that opened them). The three tests after the first describe what a
second session should get from the shared tab; they are open defects pending a
product decision (tests/open_defects.toml, shared-channel-tab).
"""

from agent_comms.channel_targets import CommandTarget


async def two_sessions_on_one_channel(workspace, ui):
    for name in (workspace.project.name, "owner-a", "owner-b"):
        workspace.thread(name, running=True)
    first = ui.selected_tab
    channel = await ui.open_channel("#all", actor="owner-a")
    second = await ui.new_session()
    assert await ui.open_channel("#all", actor="owner-b") == channel
    return first, second, channel


async def test_a_channel_has_one_tab_whichever_session_opens_it(workspace):
    async with workspace.app(size=(120, 44)) as ui:
        first, second, channel = await two_sessions_on_one_channel(workspace, ui)
        assert ui.selected_tab == channel
        assert [tab.identity for tab in ui.tabs()].count(channel) == 1
        assert await ui.open_channel("#all", actor="owner-b", owner=second) == channel


async def test_going_back_from_a_shared_channel_tab_returns_to_the_session_it_was_opened_from(workspace):
    async with workspace.app(size=(120, 44)) as ui:
        first, second, channel = await two_sessions_on_one_channel(workspace, ui)
        await ui.return_to_owner()
        assert ui.selected_tab == second


async def test_a_shared_channel_tab_sends_as_the_session_it_was_opened_from(workspace):
    async with workspace.app(size=(120, 44)) as ui:
        first, second, channel = await two_sessions_on_one_channel(workspace, ui)
        await ui.write_draft("hello shared channel")
        await ui.press("enter")

        def sent_messages():
            return tuple(message for message in workspace.comms.views.history_page(
                CommandTarget.named("#all"),
            ).messages if message.body == "hello shared channel")

        await ui.until(sent_messages, why="the message on the wire")
        assert sent_messages()[0].sender == "owner-b"


async def test_closing_one_session_keeps_the_channel_tab_another_session_opened(workspace):
    async with workspace.app(size=(120, 44)) as ui:
        first, second, channel = await two_sessions_on_one_channel(workspace, ui)
        await ui.close_tab(first)
        identities = [tab.identity for tab in ui.tabs()]
        assert first not in identities
        assert channel in identities and second in identities
