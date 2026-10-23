"""Textual-facing: a sent message whose start notice reaches the conversation after the saved history
already holds it is drawn once, by the saved history, with no second live block under it."""

from agent_comms.session_file import RegistrySessionLocation
from agent_comms.acp_extension import InputStartedUpdate, encode_updates
from agent_comms.threads import Thread

from support import agents, journals

TOKEN = "SENT_MESSAGE_DRAWN_ONCE"
INPUT = "48f2a16604c080283204f81ab5f151f4"


async def test_a_start_notice_after_the_saved_history_draws_the_message_once(workspace):
    journal = journals.write_journal(
        workspace.project / "native.jsonl",
        journals.assistant_entry("An earlier answer.", id="earlier"),
        journals.user_entry(TOKEN, id="sent", parent="earlier", input_id=INPUT))
    workspace.comms.registry.declare(
        Thread("source", frozenset(), str(workspace.project), session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    async with workspace.app(size=(110, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent("source")
        ui.attach_agent(agent)
        # The page read finds the message in the session file before Core's start notice arrives.
        await view.transcript.snapshot(workspace.comms.transcripts.thread_transcript_page("source"))
        await ui.until(lambda: ui.painted(view.window).count(TOKEN) == 1, why="the saved message")

        await agents.deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(InputStartedUpdate(None, TOKEN, None, None, INPUT))})
        await ui.step(.5)

        assert ui.painted(view.window).count(TOKEN) == 1, ui.painted(view.window)
