"""Textual-facing: a sent message whose start notice reaches the conversation after the saved history
already holds it is drawn once, by the saved history, with no second live block under it."""

from agent_comms.repo import Checkout
from functools import partial

from agent_comms.acp_extension import (
    NoQueueScope,
    UnidentifiedInputStarted,
    encode_updates,
)
from agent_comms.nominal.field_codec import InputId
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
from support import agents, journals

from toad.screens.main import MainScreen
from toad.tab_identity.kinds import MailboxTab

TOKEN = "SENT_MESSAGE_DRAWN_ONCE"
INPUT = "48f2a16604c080283204f81ab5f151f4"


async def test_a_start_notice_after_the_saved_history_draws_the_message_once(workspace):
    journal = journals.write_journal(
        workspace.project / "native.jsonl",
        journals.assistant_entry("An earlier answer.", id="earlier"),
        journals.user_entry(TOKEN, id="sent", parent="earlier", input_id=INPUT))
    owner = workspace.comms.registry.declare(
        Thread("source", frozenset(), Checkout(workspace.project), session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    async with workspace.app(size=(110, 35)) as ui:
        root = str(workspace.comms.root)
        await ui.app.session_navigation.new(
            MailboxTab(owner.incarnation, root),
            partial(MainScreen.from_thread, workspace.project, root, owner.incarnation),
            original=(root, owner.incarnation),
        )
        view = ui.conversation
        agent = ui.detached_agent("source")
        ui.attach_agent(agent)
        # Opening the retained owner reads its message before Core's start notice arrives.
        await ui.until(lambda: ui.painted(view.window).count(TOKEN) == 1, why="the saved message")

        await agents.deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(
                UnidentifiedInputStarted(TOKEN, NoQueueScope(), None, InputId(INPUT)))})
        await ui.step(.5)

        assert ui.painted(view.window).count(TOKEN) == 1, ui.painted(view.window)
