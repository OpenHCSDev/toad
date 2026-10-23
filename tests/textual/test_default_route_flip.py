"""Published defaults select fresh launches; a running application's root stays explicit."""

import asyncio
import threading
from unittest.mock import patch

import pytest
from agent_comms.active_route import ActiveRoute
from agent_comms.errors import HumanClaimBlockedError, HumanSendRefusedError, RelationViolationError
from agent_comms.launch_root import LaunchRoot
from agent_comms.route_selection import current_root

from support.routes import private_root, publish_route, route_home
from toad.wire_history import WireSource
from toad.widgets.comms_chat import CommsChatView


async def test_a_published_default_does_not_rebind_a_running_app_or_its_acquired_read(workspace, monkeypatch):
    home = route_home(monkeypatch, workspace.roots.attempt)
    first = private_root(workspace.roots.attempt / "first", workspace.project, "FIRST_HISTORY")
    second = private_root(workspace.roots.attempt / "second", workspace.project, "SECOND_HISTORY")
    publish_route(home, first)
    with ActiveRoute.published_launch().selected():
        async with workspace.app(size=(115, 38)) as ui:
            await ui.open_channel("#team", actor="user")
            await ui.until_shows("FIRST_HISTORY")
            view = ui.app.selected_session.query_one(CommsChatView)
            source = view.message_history.page_source.loader
            entered, release = threading.Event(), threading.Event()
            read = WireSource.read

            def held_read(source, request, through):
                entered.set()
                assert release.wait(8), "the acquired page was not released"
                return read(source, request, through)

            with patch.object(WireSource, "read", held_read):
                try:
                    source.comms.messaging.send("peer", "#team", "FIRST_LATE_PAGE")
                    await view._refresh()
                    assert await asyncio.to_thread(entered.wait, 8)
                    publish_route(home, second)
                    assert ActiveRoute.published_launch().path == second
                    assert current_root() == first
                    release.set()
                    await ui.until_shows("FIRST_LATE_PAGE")
                    assert ui.app.coordination_access.observation.observed().service.root == first
                    assert not ui.shows("SECOND_HISTORY")
                finally:
                    release.set()


async def test_a_fresh_launch_uses_the_published_root_and_preserves_refused_and_blocked_drafts(workspace, monkeypatch):
    from toad.core import input_events

    home = route_home(monkeypatch, workspace.roots.attempt)
    first = private_root(workspace.roots.attempt / "first", workspace.project, "FIRST_HISTORY")
    second = private_root(workspace.roots.attempt / "second", workspace.project, "SECOND_HISTORY")
    publish_route(home, first)
    with ActiveRoute.published_launch().selected():
        async with workspace.app(size=(115, 38)) as ui:
            await ui.open_channel("#team", actor="user")
            await ui.until_shows("FIRST_HISTORY")
            publish_route(home, second)
            assert ui.app.coordination_access.launch_root.path == first

    with ActiveRoute.published_launch().selected():
        async with workspace.app(size=(115, 38)) as ui:
            await ui.open_channel("#team", actor="user")
            await ui.until_shows("SECOND_HISTORY")
            view = ui.app.selected_session.query_one(CommsChatView)
            source = view.message_history.page_source.loader
            assert source.comms.root == second
            assert not ui.shows("FIRST_HISTORY")
            with patch.object(source.comms.messaging, "send_user_message",
                              side_effect=HumanSendRefusedError(RelationViolationError("pre-append rejection"))) as rejected:
                await view.submit_input(input_events.UserInputSubmitted("EDITABLE_REJECTION"))
                await ui.until(lambda: not view.prompt.prompt_text_area.disabled,
                               why="the rejected draft editable on the fresh root")
                assert rejected.call_count == 1
                assert view.prompt.text == "EDITABLE_REJECTION"
                assert not view.prompt.prompt_text_area.disabled
                assert not view.send_block_reason
            view.prompt.text = ""
            with patch.object(source.comms.messaging, "send_user_message",
                              side_effect=HumanClaimBlockedError("prior reservation cannot be retried")) as sender:
                event = input_events.UserInputSubmitted("BLOCKED_NO_RETRY")
                await view.submit_input(event)
                await ui.until(lambda: view.prompt.prompt_text_area.disabled,
                               why="the blocked send visibly holds compose")
                assert sender.call_count == 1
                assert view.send_block_reason == "Send blocked: prior reservation cannot be retried"
                assert view.prompt.text == event.body
                assert view.prompt.prompt_text_area.disabled
                await view.submit_input(event)
                assert sender.call_count == 1
            assert LaunchRoot.current().path == second
