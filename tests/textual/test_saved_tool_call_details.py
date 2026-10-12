"""Textual-facing: a tool call or coordination context in saved thread history opens to show what it holds, by a click on its line or Space on the message cursor, and closes the same way."""

from agent_comms.transcript_events import (
    AssistantTranscript, ContextTranscript, ToolEndTranscript, ToolStartTranscript,
)
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.transcript_fragments import ToolTranscriptFragment
from toad.widgets.transcript_history import TranscriptHistory


def saved_page():
    cursor = TranscriptCursor("fixture", 1)
    return TranscriptPage((
        AssistantTranscript("BEFORE_THE_TOOL"),
        ContextTranscript("CONTEXT_GIVEN_TO_THE_AGENT"),
        ToolStartTranscript(tool_call_id="call-1", tool_name="bash", raw_input={"command": "ls"}),
        ToolEndTranscript(tool_call_id="call-1", tool_name="bash", text="OUTPUT_LINE_ONE\nOUTPUT_LINE_TWO"),
        AssistantTranscript("AFTER_THE_TOOL"),
    ), cursor, cursor, False, False)


async def test_a_saved_tool_call_and_context_open_and_close_by_click_and_by_space(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        view = ui.conversation
        history = TranscriptHistory(saved_page())
        await view.post(history)
        await ui.until_shows("AFTER_THE_TOOL")
        assert ui.shows("▶ bash") and not ui.shows("OUTPUT_LINE_ONE")

        await ui.click("▶ bash")
        await ui.until(lambda: ui.shows("▼ bash") and ui.shows("OUTPUT_LINE_ONE") and ui.shows("OUTPUT_LINE_TWO"),
                       why="the tool call's output under its line")
        assert ui.shows("BEFORE_THE_TOOL") and ui.shows("AFTER_THE_TOOL")
        await ui.click("▼ bash")
        await ui.until(lambda: ui.shows("▶ bash") and not ui.shows("OUTPUT_LINE_ONE"), why="the output hidden again")

        await ui.click("▶ Agent coordination context")
        await ui.until_shows("CONTEXT_GIVEN_TO_THE_AGENT")
        assert not ui.shows("OUTPUT_LINE_ONE"), "opening one fragment opens no other"
        await ui.click("▼ Agent coordination context")
        await ui.until(lambda: not ui.shows("CONTEXT_GIVEN_TO_THE_AGENT"), why="the context hidden again")

        # Space on the message cursor does what the click does.
        await ui.press("alt+up")
        while not isinstance(view.navigation.cursor.fragment, ToolTranscriptFragment):
            await ui.press("alt+up")
        assert view.cursor_block is history and history.can_expand()
        await ui.press("space")
        await ui.until_shows("OUTPUT_LINE_TWO")
        assert history.is_block_expanded()
        await ui.press("space")
        await ui.until(lambda: not ui.shows("OUTPUT_LINE_TWO"), why="the output hidden by Space")
        assert ui.failure() is None
