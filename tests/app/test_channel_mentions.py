"""Completing a thread mention in a channel keeps the draft and delivers to the channel."""


async def test_mention_completion_delivery_and_link(workspace):
    workspace.thread("alpha", "team")
    workspace.thread("beta", "team")
    comms = workspace.comms
    async with workspace.app(size=(100, 35)) as ui:
        channel = await ui.open_channel("#team", actor="alpha")
        await ui.write_draft("Can @al")
        await ui.until_shows("Mention a thread")
        await ui.press("tab")
        assert ui.draft() == "Can @alpha "
        await ui.type("review this?")
        await ui.press("enter")
        await ui.until(lambda: len(comms.views.channel_history("#team")) == 1, why="the message on the wire")
        sent = comms.views.channel_history("#team")[0]
        assert sent.target == "#team" and sent.body == "Can @alpha review this?"
        assert sent.mentions[0].thread == "alpha"
        assert len(comms.bus.inbox("alpha")) == len(comms.bus.inbox("beta")) == 1
        await ui.until_shows("Can @alpha review this?")
        # The name becomes a link when the message's styled lines replace its plain ones.
        await ui.until(lambda: ui.link_at("@alpha review") == ("open_target", ("alpha",)),
                       why="the mention drawn as a link")

        await ui.write_draft("@")
        await ui.until_shows("Mention a thread")
        await ui.press("down", "tab")
        assert ui.draft() == "@beta "

        await ui.write_draft("Keep @al")
        await ui.until_shows("Mention a thread")
        await ui.press("escape")
        assert ui.selected_tab == channel and ui.draft() == "Keep @al"
        assert not ui.shows("Mention a thread")
