"""Textual-facing: an agent answer that grows by streaming stays one widget drawn as lines, reaches its last line, and does not stop typing or resizing."""

import asyncio

from toad.widgets.agent_response import AgentResponse


async def test_table_heavy_answer_stays_small_and_its_end_stays_reachable(workspace):
    async with workspace.app(size=(70, 25)) as ui:
        conversation = ui.conversation
        source = "| Name | Purpose | State |\n| --- | --- | --- |\n"
        response = await conversation.post(AgentResponse(source))
        conversation.window.anchor()
        maximum = 0
        for index in range(120):
            part = f"| Item {index} | " + "Descriptive content " * 5 + "| Ready |\n"
            source += part
            await response.append_fragment(part)
            maximum = max(maximum, len(list(response.query("*"))))
        source += "\n\nFINAL_END_SENTINEL"
        await response.append_fragment("\n\nFINAL_END_SENTINEL")
        await ui.step()
        assert response.body.text == source
        assert maximum < 300, maximum
        for width, height in ((145, 40), (70, 25), (100, 35), (70, 25)):
            await ui.resize(width, height)
            conversation.jump_to_latest()
            await ui.until_shows("FINAL_END_SENTINEL")
            assert response.virtual_size.height <= response.content_size.height


async def test_streaming_answer_does_not_block_typing_or_resizing(workspace):
    async with workspace.app(size=(70, 25)) as ui:
        conversation = ui.conversation
        response = await conversation.post(AgentResponse("start"))
        conversation.window.anchor()
        streaming = asyncio.Event()
        release = asyncio.Event()
        maximum = 0

        async def stream():
            nonlocal maximum
            index = 0
            while not release.is_set():
                await response.append_fragment(f"\n\nLive paragraph {index}: " + "content " * 12)
                streaming.set()
                maximum = max(maximum, len(list(response.query("*"))))
                index += 1
                await asyncio.sleep(.02)
            await response.append_fragment("\n\nSTREAM_END_SENTINEL")
            await response.finish_stream()

        stream_task = asyncio.create_task(stream())
        try:
            await streaming.wait()
            conversation.prompt.focus()
            await ui.press("d", "r", "a", "f", "t")
            assert ui.draft() == "draft"
            for width, height in ((145, 40), (70, 25), (100, 35)):
                await ui.resize(width, height)
                assert ui.textual[0].screen.size == (width, height)
        finally:
            release.set()
            await stream_task
        conversation.jump_to_latest()
        await ui.until_shows("STREAM_END_SENTINEL")
        assert maximum < 300, maximum
        assert ui.draft() == "draft"
