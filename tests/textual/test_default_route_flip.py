"""Textual-facing: an open chat keeps its startup route; a later launch selects the newly published route."""

from agent_comms.active_route import ActiveRoute
from agent_comms.comms import Comms
from agent_comms.launch_root import LaunchRoot
from agent_comms.route_selection import RouteSelection

from support.routes import private_root, publish_route, select_root_by_default_route


async def test_open_chat_keeps_its_route_and_a_new_launch_selects_the_published_route(
    workspace, monkeypatch
):
    home = select_root_by_default_route(monkeypatch, workspace.roots.attempt)
    first, first_id = private_root(
        workspace.roots.attempt / "first", workspace.project, "OLD-WIRE-ONLY"
    )
    second, second_id = private_root(
        workspace.roots.attempt / "second", workspace.project, "NEW-WIRE-ONLY"
    )
    publish_route(home, first, first_id)

    with LaunchRoot.current().selected():
        LaunchRoot.startup([], ActiveRoute.published_launch)
        async with workspace.app(size=(115, 38)) as ui:
            app, _ = ui.textual
            owner = ui.selected_tab
            mode = await ui.open_channel("#team", actor="user")
            chat = ui.conversation
            await ui.until_shows("OLD-WIRE-ONLY")
            await ui.write_draft("THE FIRST ROUTE DRAFT")

            publish_route(home, second, second_id)
            Comms(first).messaging.send("peer", "#team", "FIRST ROUTE STILL LIVE")
            await ui.until_shows("FIRST ROUTE STILL LIVE")
            assert RouteSelection.capture().root == first
            assert app.coordination_access.observation.observed().service.root == first
            assert not ui.shows("NEW-WIRE-ONLY")
            await ui.select_tab(owner)
            await ui.select_tab(mode)
            assert ui.conversation is chat
            assert ui.draft() == "THE FIRST ROUTE DRAFT"
            await ui.until_shows("FIRST ROUTE STILL LIVE")

        LaunchRoot.startup([], ActiveRoute.published_launch)
        async with workspace.app(size=(115, 38)) as ui:
            app, _ = ui.textual
            await ui.open_channel("#team", actor="user")
            await ui.until_shows("NEW-WIRE-ONLY")
            assert RouteSelection.capture().root == second
            assert app.coordination_access.observation.observed().service.root == second
            assert not ui.shows("OLD-WIRE-ONLY")
            assert not ui.shows("FIRST ROUTE STILL LIVE")
            assert ui.draft() == ""
