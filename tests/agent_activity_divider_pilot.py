"""Agent activity is visibly separated from the preceding user message."""

import asyncio
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from runtime_fixture import ToadApp

from toad.acp import messages as acp
from toad.widgets.agent_thought import AgentThought
from toad.widgets.message_divider import AgentActivityDivider, MessageDivider
from toad.widgets.message_filter import ALL_CATEGORIES, MessageCategory
from toad.widgets.transcript_fragments import transcript_fragments
from toad.widgets.transcript_history import TranscriptPageView
from toad.widgets.user_input import UserInput


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-activity-divider-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            await view.post(UserInput("Please prepare the worktree"))
            await view.on_turn_started(acp.TurnStarted("first"))
            assert not view.contents.query(AgentActivityDivider), "Empty turns should not create headers"
            await view.on_acp_agent_thinking(acp.Thinking("text", "Preparing the worktree"))
            await pilot.pause()
            thought = view.contents.query_one(AgentThought)
            children = list(view.contents.children)
            previous = children[children.index(thought) - 1]
            assert isinstance(previous, MessageDivider) and previous.label == "Agent", (
                "Thinking began without an Agent separator after User", children,
            )
            assert previous.region.bottom <= thought.region.y
            assert previous.render().cell_length == previous.size.width
            await view.on_acp_agent_thinking(acp.Thinking("text", "\nNext step"))
            tool = {"toolCallId": "first-tool", "title": "Read fixture", "status": "in_progress"}
            await view.on_acp_tool_call_update(acp.ToolCall(tool))
            await view.on_acp_tool_call_update(acp.ToolCallUpdate({**tool, "status": "completed"}, {}))
            await view.on_acp_agent_thinking(acp.Thinking("text", "Check the result"))
            assert len(view.contents.query(AgentActivityDivider)) == 1

            await view.on_input_started(acp.InputStarted("A follow-up in the same live turn"))
            await view.on_turn_started(acp.TurnStarted("first"))
            await view.on_acp_agent_thinking(acp.Thinking("text", "Process the follow-up"))
            await view.on_turn_started(acp.TurnStarted("first"))
            await view.on_acp_agent_thinking(acp.Thinking("text", "\nStill the same activity"))
            assert len(view.contents.query(AgentActivityDivider)) == 2

            await view.post(UserInput("Use a tool first"))
            await view.on_turn_started(acp.TurnStarted("tool-first"))
            tool = {"toolCallId": "second-tool", "title": "Read first", "status": "in_progress"}
            await view.on_acp_tool_call_update(acp.ToolCall(tool))
            await pilot.pause()
            headers = list(view.contents.query(AgentActivityDivider))
            assert len(headers) == 3 and headers[-1].message_category is MessageCategory.TOOL
            view.visible_categories = ALL_CATEGORIES - {MessageCategory.THINKING}
            await pilot.pause()
            assert not headers[0].display and not headers[1].display and headers[2].display
            view.visible_categories = ALL_CATEGORIES - {MessageCategory.TOOL}
            await pilot.pause()
            assert headers[0].display and not headers[2].display
            view.visible_categories = ALL_CATEGORIES

            await view.post(UserInput("Answer with text first"))
            await view.on_turn_started(acp.TurnStarted("text-first"))
            await view.on_acp_agent_message(acp.Update("text", "Text reply"))
            await view.on_acp_agent_thinking(acp.Thinking("text", "Later activity"))
            assert len(view.contents.query(AgentActivityDivider)) == 3, "Text already carries an Agent header"

            long_thought = "\n\n".join(f"Step {index}: " + "reasoning " * 30 for index in range(10))
            events = (
                TranscriptEvent("user", "Saved request"),
                TranscriptEvent("thinking", long_thought),
                TranscriptEvent("tool_start", tool_call_id="saved-1", tool_name="read"),
                TranscriptEvent("tool_end", "done", tool_call_id="saved-1", tool_name="read"),
                TranscriptEvent("thinking", "After tool"),
                TranscriptEvent("assistant", "Saved response"),
                TranscriptEvent("user", "Saved follow-up"),
                TranscriptEvent("tool_start", tool_call_id="saved-2", tool_name="read"),
                TranscriptEvent("tool_end", "done", tool_call_id="saved-2", tool_name="read"),
            )
            fragments = transcript_fragments(events)
            assert sum(fragment.starts_agent_activity for fragment in fragments) == 2
            assert not any(fragment.starts_agent_activity and fragment.continuation for fragment in fragments)
            cursor = TranscriptCursor("fixture", 0)
            saved = TranscriptPageView(TranscriptPage(events, cursor, cursor, False, False),
                                       newest=False, fragments=fragments)
            await view.post(saved)
            while saved.stop < len(fragments):
                await saved.extend(False)
            await pilot.pause()
            assert len(saved.query(AgentActivityDivider)) == 2
            first = next(child for child in saved.children if child.fragment.starts_agent_activity)
            leaf, divider = first.query_one(AgentThought), first.query_one(AgentActivityDivider)
            updated_event = replace(first.fragment.events[0], text="Updated first thought")
            await first.update_fragment(replace(first.fragment, events=(updated_event,)))
            assert first.query_one(AgentThought) is leaf
            assert first.query_one(AgentActivityDivider) is divider, "Text update remounted the header"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Agent activity: live thinking/tool-first, follow-ups, no duplicate chunks, category filters, saved continuations")


if __name__ == "__main__":
    asyncio.run(main())
