"""Textual-facing: file references in line-drawn agent text carry hyperlinks, open a preview tab on click and offer a copy-path menu on right-click."""

from unittest.mock import patch

from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.agent_response import AgentResponse
from toad.widgets.project_panel import FilePreview


def project_plan(workspace):
    path = workspace.project / "plans" / "tag-channel-view-plan.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Previewed plan\n\nResolved from chat.")
    return path.resolve()


async def say(ui, text):
    response = await ui.conversation.post(AgentResponse(text))
    await ui.until(lambda: response.body._styled is not None, why="the response drawn with its styling")
    return response


async def test_existing_project_paths_in_agent_text_are_links_and_other_text_is_not(workspace):
    path = project_plan(workspace)
    async with workspace.app(size=(130, 35)) as ui:
        await say(ui, "See plans/tag-channel-view-plan.md:\n\n`plans/tag-channel-view-plan.md`\n\n"
                      "but not plans/missing.md\n\nor https://example.com/plans/tag-channel-view-plan.md.")
        assert ui.hyperlink_at("plans/tag-channel-view-plan.md:", occurrence=0) == f"toad-file:{path}"
        assert ui.hyperlink_at("plans/tag-channel-view-plan.md", occurrence=1) == f"toad-file:{path}"
        assert ui.hyperlink_at("plans/missing.md") is None
        assert ui.hyperlink_at("https://example.com/plans/tag-channel-view-plan.md.") is None


async def test_explicit_links_name_the_file_search_or_the_website(workspace):
    path = project_plan(workspace)
    async with workspace.app(size=(130, 35)) as ui:
        await say(ui, f"[Absolute]({path}) [Relative](plans/tag-channel-view-plan.md) "
                      "[Website](https://example.com/preview.py) [Missing](missing.py)")
        assert [ui.hyperlink_at(name) for name in ("Absolute", "Relative", "Website", "Missing")] == [
            f"toad-file:{path}", f"toad-file:{path}",
            "https://example.com/preview.py", "toad-file-search:missing.py"]


async def test_clicking_a_file_link_opens_its_preview_tab(workspace):
    path = project_plan(workspace)
    async with workspace.app(size=(130, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await ui.write_draft("Keep this draft")
        await say(ui, "[Relative](plans/tag-channel-view-plan.md)")
        await ui.click("Relative")
        await ui.until(lambda: ui.selected_tab != owner, why="the preview tab selected")
        preview = app.selected_session.query_one(FilePreview)
        await preview.wait_ready()
        assert preview.path == path
        await ui.select_tab(owner)
        assert ui.draft() == "Keep this draft"


async def test_right_clicking_a_file_link_offers_to_copy_its_full_path(workspace):
    path = project_plan(workspace)
    async with workspace.app(size=(130, 35)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        await say(ui, "[Relative](plans/tag-channel-view-plan.md)")
        x, y = ui._cell_of("Relative", 0)
        assert await pilot.click(offset=(x, y), button=3)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the link menu")
        with patch.object(app, "copy_to_clipboard") as copied:
            copy = next(item for item in app.screen.query(ContextMenuItem) if item.action == "copy_path")
            assert await pilot.click(copy)
            await ui.until(lambda: copied.called, why="the path copied")
            copied.assert_called_once_with(str(path))
        assert ui.selected_tab == owner


async def test_a_bare_file_name_links_to_a_search_that_opens_the_one_matching_file(workspace):
    nested = workspace.project / "src" / "agent_comms" / "declarations.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("# NESTED-DECLARATIONS-MARKER\n")
    async with workspace.app(size=(130, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await say(ui, "See declarations.py")
        assert ui.hyperlink_at("declarations.py") == "toad-file-search:declarations.py"
        await ui.click("declarations.py")
        await ui.until(lambda: ui.selected_tab != owner, why="the preview of the nested file")
        preview = app.selected_session.query_one(FilePreview)
        assert preview.path == nested.resolve()


async def test_a_bare_file_name_found_in_several_places_says_so_instead_of_guessing(workspace):
    for place in ("src/agent_comms", "other"):
        (workspace.project / place).mkdir(parents=True)
        (workspace.project / place / "declarations.py").write_text("# declaration\n")
    async with workspace.app(size=(130, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await say(ui, "See declarations.py")
        with patch.object(app, "notify") as notices:
            await ui.click("declarations.py")
            await ui.until(lambda: notices.called, why="a notice about the ambiguous name")
            assert "Several files named declarations.py" in notices.call_args.args[0]
        assert ui.selected_tab == owner
