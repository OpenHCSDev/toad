"""Textual-facing: a thread's saved history is drawn from render-worker results, and while those are pending Textual keeps the draft box typeable and the tab switchable."""

import asyncio

from support.textual_steps import replay_with_pending_render
from toad.widgets.conversation import ThreadLoading


async def test_typing_stays_live_while_replay_rendering_is_pending(workspace):
    async with replay_with_pending_render(workspace) as (ui, owner, mode, release):
        conversation = ui.conversation
        conversation.prompt.focus()
        await asyncio.wait_for(ui.type("draft"), 2)
        assert ui.draft() == "draft"
        release()
        await ui.until(lambda: conversation.agent_ready, seconds=15, why="the replay to be ready")
        await ui.until_shows("PREPARED_REPLAY_END")
        await ui.until(lambda: not conversation.query(ThreadLoading), why="the loading indicator to go")
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
        await ui.until(lambda: not conversation.query(ThreadLoading), why="the loading indicator to go")
        await ui.until_shows("PREPARED_REPLAY_END")
        assert ui.draft() == "draft"
