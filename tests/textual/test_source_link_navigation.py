"""Textual-facing: clicking a source-file link in agent text opens the file in the workspace, survives a resize, and returning restores the same editor."""

from toad.widgets.agent_response import AgentResponse
from toad.widgets.project_panel import FilePreview


async def test_source_link_opens_the_file_and_returning_restores_the_editor(workspace):
    target = workspace.project / "navigation-proof.txt"
    target.write_text("SOURCE_NAVIGATION_FILE_PAINT\n")
    async with workspace.app(size=(100, 32)) as ui:
        app, _ = ui.textual
        frame, owner = app.screen, app.selected_session
        conversation = owner.conversation
        editor = conversation.prompt.prompt_text_area
        editor.insert("retained navigation draft")
        editor.history.checkpoint()
        editor.insert(" with undo")
        document, history = editor.document, editor.history
        response = await conversation.post(AgentResponse(""))
        await response.append_fragment(f"[Open source file]({target})")
        await ui.until(lambda: ui.shows("Open source file") and not ui.shows("]("), seconds=15,
                       why="the Markdown link to be drawn as a link")
        await ui.click("Open source file")
        await ui.until(lambda: app.screen.query(FilePreview), seconds=10, why="the file preview")
        await app.screen.query_one(FilePreview).wait_ready()
        await ui.step()
        assert app.screen is frame
        await ui.resize(72, 26)
        painted = "\n".join(strip.text for strip in frame._compositor.render_strips())
        assert "SOURCE_NAVIGATION_FILE_PAINT" in painted
        await ui.select_tab(owner.id)
        restored = owner.conversation.prompt.prompt_text_area
        assert restored is editor
        assert restored.document is document and restored.history is history
        restored.undo()
        assert restored.text == "retained navigation draft"
        assert app.screen is frame
