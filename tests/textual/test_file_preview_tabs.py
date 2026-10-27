"""Textual-facing: a file preview is a closeable tab whose FilePreview widget is retained, highlighted and bounded in size."""

from toad.widgets.line_markdown import LineMarkdown
from toad.session_actions import ReturnToViewAction
from textual.document._editing import EditingMode
from toad.widgets.project_panel import FilePreview
from toad.widgets.session_tabs import SessionTabClose


def write_plan(workspace):
    path = workspace.project / "plans" / "tag-channel-view-plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Previewed plan\n\nResolved from chat.")
    return path


async def preview(ui, path):
    """Open `path` in its tab and wait until its content is loaded; return the tab and the widget."""
    app, _ = ui.textual
    mode = await app.session_navigation.preview(path)
    widget = app.selected_session.query_one(FilePreview)
    await widget.wait_ready()
    await ui.step()
    return mode, widget


async def test_opening_a_file_adds_a_tab_named_for_it_and_opening_it_again_selects_that_tab(workspace):
    path = write_plan(workspace)
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await ui.write_draft("Keep this draft")
        mode, widget = await preview(ui, path)
        assert [tab.identity for tab in ui.tabs()][:2] == [owner, mode]
        assert widget.path == path.resolve()
        assert str(path.resolve()) in widget.query_one(".file-preview-path").render().plain
        assert "Previewed plan" in widget.query_one(LineMarkdown).text
        assert next(tab.title for tab in ui.tabs() if tab.identity == mode) == path.name
        assert app.screen.query_one(f"#close-{mode}", SessionTabClose)
        assert app.session_tracker.session_count == 1
        await ui.select_tab(owner)
        assert ui.draft() == "Keep this draft"
        assert await app.session_navigation.preview(path) == mode
        assert app.selected_session.query_one(FilePreview) is widget, "Opening a file twice duplicated its view"
        assert [tab.identity for tab in ui.tabs()].count(mode) == 1


async def test_closing_a_preview_leaves_the_selected_file_and_the_agent_intact(workspace):
    path = write_plan(workspace)
    other = workspace.project / "other.py"
    other.write_text("answer = 42\n")
    async with workspace.app(size=(110, 35)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        await ui.write_draft("Keep this draft")
        first, _ = await preview(ui, path)
        second, _ = await preview(ui, other)
        assert second != first and ui.selected_tab == second
        assert [tab.identity for tab in ui.tabs()][:3] == [owner, first, second]
        await ui.until_shows("answer = 42")
        assert await pilot.click(f"#close-{first}")
        await ui.until(lambda: first not in {tab.identity for tab in ui.tabs()}, why="the first preview closed")
        assert ui.selected_tab == second
        assert await pilot.click(f"#close-{second}")
        await ui.until(lambda: ui.selected_tab == owner, why="the owner tab selected after closing the last preview")
        assert ui.draft() == "Keep this draft"
        assert not app.selected_session.query(FilePreview)


async def test_back_returns_to_the_previous_tab_without_closing_the_preview(workspace):
    path = write_plan(workspace)
    other = workspace.project / "other.py"
    other.write_text("answer = 42\n")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await ui.write_draft("Keep this draft")
        first, first_widget = await preview(ui, path)
        second, _ = await preview(ui, other)
        assert [tab.identity for tab in ui.tabs()][:3] == [owner, first, second]
        app.set_keymap({ReturnToViewAction.binding_id(EditingMode): "f10"})
        await ui.press("escape")
        assert ui.selected_tab == second
        await ui.press("f10")
        await ui.step()
        assert ui.selected_tab == first
        assert app.selected_session.query_one(FilePreview) is first_widget
        assert second in {tab.identity for tab in ui.tabs()}
        await ui.select_tab(second)
        await ui.press("ctrl+w")
        await ui.step()
        assert ui.selected_tab == first
        await app.session_navigation.close(first)
        await ui.step()
        assert ui.selected_tab == owner
        assert ui.draft() == "Keep this draft"


async def test_large_python_file_is_highlighted_and_shown(workspace):
    large = workspace.project / "preview.py"
    large.write_text("# UTF-8: café\n\n" + "def check(value: int) -> int:\n    return value + 1\n\n" * 2400)
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        mode, _ = await preview(ui, large)
        await ui.until_shows("def check(value: int) -> int:")
        assert ui.selected_tab == mode
        await app.session_navigation.close(mode)
        await ui.step()
        assert ui.selected_tab == owner


async def test_oversized_file_shows_its_first_part_and_says_so(workspace):
    oversized = workspace.project / "oversized-preview.py"
    oversized.write_text("# FIRST-LINE-MARKER\nanswer = 42\n" + "pass\n" * 230_000)
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        mode, _ = await preview(ui, oversized)
        await ui.until_shows("exceeds 1 MiB; showing only the first 64 KiB")
        assert ui.shows("FIRST-LINE-MARKER")
        assert ui.selected_tab == mode
        await app.session_navigation.close(mode)
        await ui.step()
        assert ui.selected_tab == owner


async def test_log_file_is_previewed(workspace):
    log = workspace.project / "session.log"
    log.write_text("LOG-PREVIEW-WORKS\n")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        mode, _ = await preview(ui, log)
        await ui.until_shows("LOG-PREVIEW-WORKS")
        await app.session_navigation.close(mode)
        await ui.step()
        assert ui.selected_tab == owner


async def test_preview_opened_from_a_channel_sits_above_it_and_closing_returns_to_the_channel(workspace):
    path = write_plan(workspace)
    workspace.thread("project")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        await ui.write_draft("Keep this draft")
        channel = await ui.open_channel("#all", actor="project")
        mode, widget = await preview(ui, path)
        assert widget.path == path.resolve()
        assert [tab.identity for tab in ui.tabs()] == [owner, channel, mode]
        await app.session_navigation.close(mode)
        await ui.step()
        assert ui.selected_tab == channel
        await ui.select_tab(owner)
        assert ui.draft() == "Keep this draft"
