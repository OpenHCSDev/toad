"""Textual-facing: the conversation widget draws a submitted message before its slow history write finishes."""

import asyncio

from support.agents import peer
from toad.widgets.user_input import UserInput


async def test_submission_is_drawn_before_slow_history_persistence_finishes(workspace):
    async with workspace.app(agent=peer("echo")) as ui:
        await ui.until_agent_ready()
        conversation = ui.conversation
        gate = asyncio.Event()
        started = asyncio.Event()

        async def slow_append(_text):
            started.set()
            await gate.wait()
            return True

        conversation.input_histories.prompt.append = slow_append
        await ui.write_draft("Show this before persistence finishes")
        sending = asyncio.create_task(ui.press("enter"))
        await asyncio.wait_for(started.wait(), 2)
        await ui.until(lambda: any("Show this before" in block.content for block in conversation.query(UserInput)),
                       why="the submitted message drawn while persistence is blocked")
        assert not gate.is_set()
        gate.set()
        await sending
