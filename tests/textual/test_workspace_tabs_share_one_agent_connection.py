"""Textual-facing: tabs of one workspace screen (Textual-hosted sessions) attach to the same agent process, and closing one leaves it for the other."""

import asyncio
from functools import partial

from support.shared_stdio import stdio_agent_definition, threads_owned_here

from toad.app import ToadApp
from toad.screens.main import MainScreen
from toad.session_scope import AgentAttached, AgentSession
from support.ui import saved_tab


async def ready(agent):
    async with asyncio.timeout(10):
        await agent.session.settled.wait()
    assert agent.ready


async def test_a_second_tab_reuses_the_first_tabs_agent_process_and_closing_it_keeps_the_process(
    workspace, monkeypatch
):
    # The agent's model catalogue comes from this variable instead of a native package.
    monkeypatch.setenv("AGENT_COMMS_AGENT_MODELS", "test/one")
    project, comms, definition = (
        workspace.project,
        workspace.comms,
        stdio_agent_definition(),
    )
    async with threads_owned_here(comms, project):
        application = partial(ToadApp, agent_session_id="alpha")
        async with workspace.app(
            size=(110, 36), binding=AgentAttached(definition), application=application
        ) as ui:
            app, _pilot = ui.textual
            await ui.until(
                lambda: app.selected_session.presentation.operational_binding.ready,
                why="the first tab's agent",
            )
            source = app.selected_session
            first = source.presentation.operational_binding
            await ready(first)
            connection = first.process
            owner_tab = ui.selected_tab
            details = await app.session_navigation.new(
                await saved_tab(app),
                lambda: MainScreen(app.project_dir, AgentSession(definition, "beta"))
            )
            second_source = app.workspace_sessions.require(details.mode_name)
            await ui.until(
                lambda: second_source.presentation.operational_binding.ready,
                why="the second tab's agent",
            )
            second = second_source.presentation.operational_binding
            await ready(second)
            assert second.process is connection
            await ui.select_tab(owner_tab)
            assert source.presentation.operational_binding is first
            await ui.close_tab(details.mode_name)
            assert first.ready and connection.sessions == {first.session}
            assert connection.process is not None and not connection.runner.done()
            assert ui.failure() is None
        assert connection.process is None and not connection.sessions
