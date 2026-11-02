"""Permission layout keeps native focus, answers and current theme paint."""

from dataclasses import replace

from textual.color import Color

from support.workspace import Workspace
from toad.answer import Answer
from toad.screens.permissions import PermissionGrid, PermissionsScreen


async def test_permission_layout_retains_focus_theme_and_answer(workspace: Workspace) -> None:
    async with workspace.app(size=(100, 34)) as ui:
        app, _pilot = ui.textual
        answer = Answer("Allow this change", "allow", "allow_once")
        answers: list[Answer] = []
        screen = PermissionsScreen([answer], diffs=[])
        app.push_screen(screen, answers.append)
        await ui.until(lambda: screen.is_mounted and screen.question.has_focus,
                       why="the permission question owns focus")
        grid = screen.query_one(PermissionGrid)
        question = screen.question
        navigator = screen.navigator
        tool = screen.tool_container
        assert grid.region.width > 0 and grid.region.height > 0
        assert navigator.region.width >= 20
        assert navigator.region.bottom == tool.region.bottom
        focused_border = question.styles.border
        tool.focus()
        await ui.until(lambda: tool.has_focus, why="the diff area owns focus")
        assert question.styles.border != focused_border
        assert tool.styles.border == focused_border
        question.focus()
        await ui.until(lambda: question.has_focus, why="the answer control owns focus again")
        assert question.styles.border == focused_border

        previous_theme = app.theme
        next_theme = next(name for name in app.colours.schemes if name != previous_theme)
        app.theme = next_theme
        await ui.step()
        assert question.has_focus
        assert grid.styles.background == screen.styles.background == tool.styles.background
        assert question.styles.border != tool.styles.border
        app.theme = previous_theme
        await ui.step()
        assert question.styles.border == focused_border

        # Palette/variable refresh can run while the theme name stays unchanged.
        theme = app.current_theme
        app.register_theme(replace(theme, background="#213243", primary="#aabbee"))
        app.refresh_css(animate=False)
        await ui.step()
        assert app.theme == previous_theme
        assert grid.styles.background == screen.styles.background == Color.parse("#213243")
        assert question.styles.border != focused_border
        app.register_theme(theme)
        app.refresh_css(animate=False)
        await ui.step()
        assert question.styles.border == focused_border

        await ui.press("enter")
        await ui.until(lambda: bool(answers), why="the selected answer returned")
        assert answers == [answer]
