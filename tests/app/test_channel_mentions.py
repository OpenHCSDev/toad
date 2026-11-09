"""Completing a thread mention in a channel keeps the draft and delivers to the channel."""


from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.messaging.display_references import ThreadDisplayReference
from agent_comms.projects.checkouts import Checkout

from toad.line_blocks import OpenReference
from toad.link_click import OpenLineLink


async def test_mention_completion_delivery_and_link(workspace):
    alpha = workspace.thread("alpha", "team")
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
        team = ChannelTarget("#team").display_history(comms.views, Checkout(workspace.project))

        def on_the_wire():
            return team.page(comms.views.presentation).messages

        await ui.until(lambda: len(on_the_wire()) == 1, why="the message on the wire")
        sent = on_the_wire()[0]
        assert sent.target == "#team" and sent.body == "Can @alpha review this?"
        assert sent.mentions[0].thread == "alpha"
        assert len(comms.bus.inbox("alpha").page.messages) == len(comms.bus.inbox("beta").page.messages) == 1
        await ui.until_shows("Can @alpha review this?")
        # The name becomes a link when the message's styled lines replace its plain ones.
        # A mention names alpha's exact birth on this wire, not whichever thread holds the name later.
        mention = OpenLineLink(OpenReference(ThreadDisplayReference(
            root=str(workspace.roots.wire), incarnation=alpha.incarnation)))
        await ui.until(lambda: ui.link_at("@alpha review") == mention,
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
