"""Textual-facing: the "Open ACP log" link under a failed request is a Textual link target drawn with the
widget's hover link style, and the tab it opens holds the log in the log view's text area."""
from toad.session_scope import AgentAttached

import asyncio

from textual.widgets import TextArea

from support.agents import peer
from toad.project_link import AcpLogLink
from toad.widgets.acp_log import AcpLogPreview
from toad.widgets.agent_response import AgentResponse

LINK = AcpLogLink.label


async def shown_log(ui):
    app, _ = ui.textual
    await ui.until(lambda: app.screen.query(AcpLogPreview), why="the log view")
    view = app.screen.query_one(AcpLogPreview)
    await asyncio.wait_for(view.wait_ready(), 10)
    await ui.step()
    return view


async def test_the_log_link_highlights_under_the_pointer_and_opens_the_agents_log_in_one_tab(workspace):
    async with workspace.app(size=(139, 30), binding=AgentAttached(peer("refuses_initialize"))) as ui:
        app, pilot = ui.textual
        await ui.until_shows("AGENT_REFUSED_TO_START", seconds=20)
        await ui.until(lambda: ui.shows(LINK) and ui.link_at(LINK) is not None, why="the log link drawn as a link")
        owner = ui.selected_tab
        cell = ui._cell_of(LINK, 0)
        body, _ = app.screen.get_widget_at(*cell)
        resting = app.screen.get_style_at(*cell)

        await pilot.hover(offset=cell)
        await ui.until(lambda: app.screen.get_style_at(*cell) != resting, why="the link drawn differently under the pointer")
        hovered = app.screen.get_style_at(*cell)
        assert hovered.bgcolor == body.link_style_hover.bgcolor != resting.bgcolor
        assert hovered.underline == body.link_style_hover.underline
        await pilot.hover(offset=(cell[0], cell[1] - 1))
        await ui.until(lambda: app.screen.get_style_at(*cell).bgcolor == resting.bgcolor,
                       why="the link drawn as before once the pointer left it")

        await ui.click(LINK)
        await ui.until(lambda: ui.selected_tab != owner, why="the log tab selected")
        log_tab = ui.selected_tab
        view = await shown_log(ui)
        assert "AGENT_REFUSED_TO_START" in view.query_one(TextArea).text
        title = next(tab.title for tab in ui.tabs() if tab.identity == log_tab)
        assert title == f"ACP log · {view.path.stem}" and title.startswith("ACP log · Test_peer_")

        await ui.select_tab(owner)
        await ui.click(LINK)
        await ui.until(lambda: ui.selected_tab == log_tab, why="the same log tab selected again")
        assert app.screen.query_one(AcpLogPreview) is view
        assert [tab.identity for tab in ui.tabs()].count(log_tab) == 1
        assert sum(tab.title == title for tab in ui.tabs()) == 1
        assert ui.failure() is None


async def test_a_link_to_a_log_that_was_never_written_opens_the_tab_and_says_the_log_cannot_be_read(workspace):
    missing = workspace.roots.attempt / "state/toad/logs/never-written.txt"
    async with workspace.app(size=(139, 30)) as ui:
        owner = ui.selected_tab
        await ui.conversation.post(AgentResponse(AcpLogLink(missing).markdown))
        await ui.until(lambda: ui.shows(LINK) and ui.link_at(LINK) is not None, why="the log link drawn as a link")
        await ui.click(LINK)
        await ui.until(lambda: ui.selected_tab != owner, why="the log tab selected")
        view = await shown_log(ui)
        assert "Unable to read log" in view.query_one(TextArea).text
        assert ui.failure() is None
