"""Textual-facing: changing which message categories show restyles only the affected blocks, never the whole conversation."""

from unittest.mock import patch
from dataclasses import replace

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from agent_comms.thread_text import SavedSessionFile
from agent_comms.ui_model.message_category import ThinkingCategory, UserCategory, all_categories

from support.journals import assistant_entry, user_entry, write_journal
from toad.widgets.transcript_history import ProjectedTranscriptHistory


async def test_category_change_does_not_restyle_the_whole_conversation(workspace):
    async with workspace.app(size=(130, 43)) as ui:
        view = ui.conversation
        await view.contents.mount(*[
            cls(f"## Record {index}\n\n" + "A paragraph of ordinary text.\n\n" * 5)
            for index in range(30) for cls in (AgentResponse, AgentThought)
        ])
        await ui.step()
        app, _ = ui.textual
        with patch.object(app, "update_styles", wraps=app.update_styles) as styles:
            for _ in range(4):
                for selected in (all_categories() - {ThinkingCategory}, all_categories()):
                    view.visible_categories = selected
                    await ui.step()
            whole_view = sum(call.args == (view,) for call in styles.call_args_list)
        assert whole_view == 0, "Category change restyled unrelated descendants"


async def test_filtering_saved_history_paints_an_older_projection_and_returns_to_the_tail(workspace):
    journal = write_journal(workspace.project / "filtered.jsonl",
        user_entry("FILTER_USER", id="user"), *(
            assistant_entry(f"SAVED_ASSISTANT_{index}", id=f"a{index}",
                            parent=f"a{index - 1}" if index else "user")
            for index in range(300)))
    workspace.comms.registry.declare(replace(
        workspace.thread("source"), session_file=SavedSessionFile(str(journal))))
    async with workspace.app(size=(120, 35), resume="source") as ui:
        view = ui.conversation
        await ui.until(lambda: "SAVED_ASSISTANT_299" in ui.painted(view.window),
                       why="the saved source's tail")
        history = view.transcript.binding.history
        view.visible_categories = frozenset({UserCategory})
        view.window.release_anchor()
        view.window.scroll_home(animate=False, immediate=True)
        await ui.until(lambda: isinstance(history.filter.overlay, ProjectedTranscriptHistory)
                       and "FILTER_USER" in ui.painted(view.window),
                       why="the older filtered projection")
        projection = history.filter.overlay
        assert projection.conversation is view
        assert "SAVED_ASSISTANT_299" not in ui.painted(view.window)

        view.visible_categories = all_categories()
        view.window.jump_to_latest()
        await ui.until(lambda: projection not in history.children
                       and "SAVED_ASSISTANT_299" in ui.painted(view.window),
                       why="the original tail after removing the filter")
        assert ui.failure() is None
