"""Textual-facing: a thread's saved history is drawn from render-worker results, and while those are pending Textual keeps the draft box typeable and the tab switchable."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from support.agents import peer
from toad.acp.agent import Agent
from toad.core.events import AgentReady
from toad.widgets.conversation import ThreadLoading
from toad.widgets.transcript_fragments import TranscriptRenderTask


@asynccontextmanager
async def replay_with_pending_render(workspace):
    """Open the thread "replay" while its saved history waits on a held render-worker task.

    Yields (ui, owner tab, replay tab, release); `release()` lets the render finish.
    """
    workspace.thread("replay", running=True)
    events = tuple(AssistantTranscript("Paragraph.\n\n" * 100) for _ in range(20))
    events += (AssistantTranscript("PREPARED_REPLAY_END"),)
    page = TranscriptPage(events, TranscriptCursor("fixture", 0), TranscriptCursor("fixture", len(events)),
                          False, False)
    dispatch, entered, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
    shown = []

    async def start(agent, processes=()):
        async def deliver():
            await dispatch.wait()
            await shown[0].conversation.transcript.snapshot(page)
            agent.events.publish(AgentReady())

        agent.session.task = asyncio.create_task(deliver())

    try:
        with patch.object(Agent, "start", start):
            async with workspace.app(size=(110, 35), agent=peer("echo")) as ui:
                app, _ = ui.textual
                shown.append(ui)
                renderer = app.preparation.renderer
                capture = renderer.capture

                async def gated(task):
                    if isinstance(task, TranscriptRenderTask):
                        entered.set()
                        await released.wait()
                    return await capture(task)

                with patch.object(renderer, "capture", gated):
                    owner = ui.selected_tab
                    mode = await app.thread_navigation.open(owner_mode=owner, project_path=workspace.project,
                                                            target="replay")
                    await ui.step()
                    assert ui.conversation.query(ThreadLoading)
                    dispatch.set()
                    await asyncio.wait_for(entered.wait(), 3)
                    yield ui, owner, mode, released.set
    finally:
        dispatch.set()
        released.set()


async def test_typing_stays_live_while_replay_rendering_is_pending(workspace):
    async with replay_with_pending_render(workspace) as (ui, owner, mode, release):
        conversation = ui.conversation
        conversation.prompt.focus()
        await asyncio.wait_for(ui.type("draft"), 2)
        assert ui.draft() == "draft"
        release()
        await ui.until(lambda: conversation.agent_ready, seconds=15, why="the replay to be ready")
        await ui.until_shows("PREPARED_REPLAY_END")
        assert not conversation.query(ThreadLoading)
        assert ui.draft() == "draft"


async def test_leaving_and_returning_while_replay_rendering_is_pending_still_shows_the_replay(workspace):
    async with replay_with_pending_render(workspace) as (ui, owner, mode, release):
        conversation = ui.conversation
        conversation.prompt.focus()
        await asyncio.wait_for(ui.type("draft"), 2)
        assert ui.draft() == "draft"
        await asyncio.wait_for(ui.select_tab(owner), 2)
        release()
        await asyncio.wait_for(ui.select_tab(mode), 2)
        await ui.until(lambda: conversation.agent_ready, seconds=15, why="the replay to be ready")
        assert not conversation.query(ThreadLoading)
        await ui.until_shows("PREPARED_REPLAY_END")
        assert ui.draft() == "draft"
