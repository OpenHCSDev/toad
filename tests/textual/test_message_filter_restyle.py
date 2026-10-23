"""Textual-facing: changing which message categories show restyles only the affected blocks, never the whole conversation."""

from unittest.mock import patch
from dataclasses import replace

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from agent_comms.thread_text import SavedSessionFile
from agent_comms.ui_model.message_category import ThinkingCategory, UserCategory, all_categories
from agent_comms.ui_model.message_category import InboundCategory
from toad.message_rows import MarkdownMessageStyle
from toad.widgets.comms_chat import CommsChatView

from support.journals import assistant_entry, user_entry, write_journal
from toad.widgets.transcript_history import ProjectedTranscriptHistory
from toad.transcript_preparation import TranscriptPageRenderTask
from toad.transcript_state import PreparedReplacementViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.work_preparation import RenderPreparation


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

        await ui.app.coordination_access.stop_observing()
        await view.transcript.suspend()
        previous_source = history.page_source
        replacement = write_journal(workspace.project / "replacement.jsonl",
            user_entry("REPLACEMENT_FILTER_USER", id="new-user"), *(
                assistant_entry(f"REPLACEMENT_ASSISTANT_{index}", id=f"new-a{index}",
                                parent=f"new-a{index - 1}" if index else "new-user")
                for index in range(300)))
        workspace.comms.registry.declare(replace(
            workspace.comms.registry.require("source"), session_file=SavedSessionFile(str(replacement))))
        page = await ui.app.preparation.run_thread(workspace.comms.transcripts.thread_transcript_page, "source")
        prepared = await ui.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
        assert await history.show_newest(PreparedReplacementViewportRequest(
            LatestPosition.hold(view.window), prepared))
        assert previous_source.closed
        assert view.visible_categories == frozenset({UserCategory})
        assert not projection.display
        history.filter.request_older()
        await ui.until(lambda: isinstance(history.filter.overlay, ProjectedTranscriptHistory)
                       and history.filter.overlay is not projection
                       and "REPLACEMENT_FILTER_USER" in ui.painted(view.window),
                       why="the next older filtered read from the replacement source")
        projection = history.filter.overlay

        view.visible_categories = all_categories()
        view.window.jump_to_latest()
        await ui.until(lambda: projection not in history.children
                       and "REPLACEMENT_ASSISTANT_299" in ui.painted(view.window),
                       why="the original tail after removing the filter")
        assert ui.failure() is None


async def test_a_style_change_rebuilds_filtered_history_and_its_next_older_read(workspace):
    workspace.thread("sender", "style")
    for index in range(240):
        workspace.comms.messaging.send("sender", "#style", f"**STYLE_ROW_{index}**")
    async with workspace.app(size=(110, 30)) as ui:
        await ui.open_channel("#style", actor=workspace.viewer)
        chat = ui.app.selected_session.query_one(CommsChatView)
        await ui.until_shows("**STYLE_ROW_239**")
        history = chat.message_history
        chat.visible_categories = frozenset({InboundCategory})
        chat.window.release_anchor()
        chat.window.scroll_home(animate=False, immediate=True)
        history.filter.request_older()
        await ui.until(lambda: isinstance(history.filter.overlay, ProjectedTranscriptHistory)
                       and bool(history.filter.overlay.fragments_in_range),
                       why="the original filtered older messages")
        old_source, old_projection = history.page_source, history.filter.overlay
        await history.toggle_style()
        assert old_source.closed and not old_projection.display
        assert chat.visible_categories == frozenset({InboundCategory})
        await ui.until(lambda: "STYLE_ROW_239" in ui.painted(chat.window)
                       and "**STYLE_ROW_239**" not in ui.painted(chat.window),
                       why="Markdown drawing to replace the literal IRC asterisks")
        history.filter.request_older()
        await ui.until(lambda: isinstance(history.filter.overlay, ProjectedTranscriptHistory)
                       and history.filter.overlay is not old_projection
                       and bool(history.filter.overlay.fragments_in_range),
                       why="the new style's filtered older messages")
        projection = history.filter.overlay
        first = projection.pages[0].prepared.page.before
        history.filter.request_older()
        await ui.until(lambda: projection.pages[0].prepared.page.before != first,
                       why="another older read after the style change")
        assert all(isinstance(fragment.shown.style, MarkdownMessageStyle)
                   for fragment in (*history.fragments, *projection.fragments))
        assert "**STYLE_ROW_" not in ui.painted(chat.window)
        assert ui.failure() is None
