"""Textual-facing: a thread opened cold shows its loading indicator, then its saved history, and keeps its draft through repeated returns to its tab, with and without background output."""

import asyncio

from agent_comms.transcript_events import AssistantTranscript

from support.textual_steps import replay_with_pending_render
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import ThreadLoading


def saved_records():
    body = "## Saved response\n\n" + "Paragraph **with markup** and content.\n\n" * 10
    body += "```python\n" + "def calculate(value): return value + 1\n" * 60 + "```\n"
    return tuple(AssistantTranscript(f"Record {i}\n\n" + body) for i in range(30)) + (
        AssistantTranscript("LATEST_REPLAY_MARKER"),)


async def test_cold_thread_shows_replay_and_keeps_draft_through_returns(workspace):
    async with replay_with_pending_render(workspace, saved_records()) as (ui, owner, mode, release):
        conversation = ui.conversation
        assert conversation.query(ThreadLoading), "Replay gate did not preserve loading UI"
        release()
        await ui.until(lambda: conversation.agent_ready, seconds=20, why="the replay to be ready")
        await ui.until_shows("LATEST_REPLAY_MARKER", seconds=20)
        await ui.until(lambda: not conversation.query(ThreadLoading), why="the loading indicator to go")
        conversation.prompt.text = "retained draft"
        for updated in (False, True, False, True):
            await ui.select_tab(owner)
            if updated:
                response = await conversation.post(AgentResponse("Background output."))
                await response.append_fragment("\n\nNew background paragraph.")
            await ui.step()
            await ui.select_tab(mode)
            assert ui.draft() == "retained draft"
            if updated:
                await ui.until_shows("New background paragraph.")
