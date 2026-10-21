"""Textual-facing: a mounted chat view (widget state: display, composer, status) follows the default comms route when it flips."""

import asyncio
import threading
from unittest.mock import patch

from agent_comms.errors import HumanClaimBlockedError
from agent_comms.route_selection import root_is_current

from support.routes import private_root, publish_route, select_root_by_default_route
from support.textual_steps import refresh_chat
from toad.wire_history import WireSource


async def test_a_late_read_from_the_former_wire_is_not_painted_after_the_route_flips(workspace, monkeypatch):
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.comms_sidebar import CommsSidebar

    attempt = workspace.roots.attempt
    home = select_root_by_default_route(monkeypatch, attempt)
    first, first_id = private_root(attempt / "first", workspace.project, "OLD-WIRE-ONLY")
    second, second_id = private_root(attempt / "second", workspace.project, "NEW-WIRE-ONLY")
    publish_route(home, first, first_id)

    async with workspace.app(size=(115, 38)) as ui:
        app = ui.textual[0]
        assert app.coordination_access.service.root == first
        mode = await ui.open_channel("#team", actor="user")
        assert mode == ui.selected_tab
        view = app.screen.query_one(CommsChatView)
        await refresh_chat(view)
        await ui.step()
        assert view.message_history.source.comms.root == first
        assert any("OLD-WIRE-ONLY" in str(message) for message in view.message_history.messages), view.message_history.messages

        # A read already in flight when the route flips must not paint a late page
        # from the former wire into the successor view.
        view.message_history.source.comms.messaging.send_initial_cohort("peer", "#team", "LATE-OLD-EDGE")
        entered, release = threading.Event(), threading.Event()
        real_read = WireSource.read

        def delayed_read(source, request, through):
            entered.set()
            assert release.wait(8), "the held read was not released"
            return real_read(source, request, through)

        with patch.object(WireSource, "read", delayed_read):
            pending = asyncio.create_task(refresh_chat(view))
            assert await asyncio.to_thread(entered.wait, 5)
            publish_route(home, second, second_id)
            release.set()
            await pending
            await ui.until(lambda: view.message_history.state.accepts_source_work, why="the held read to end")
        # The route check runs once a second; the app's observed service follows it.
        await ui.until(lambda: app.coordination_access.service.root == second, why="the app to follow the route")
        assert all("LATE-OLD-EDGE" not in str(message) for message in view.message_history.messages)
        await refresh_chat(view)
        async with asyncio.timeout(10):
            await app.coordination_access.current_sidebar()
        await ui.step()
        assert not root_is_current(first)
        assert not view.display
        if app.screen.query_one(CommsSidebar).display:
            # The shared roster may already publish the successor while this old view stays hidden.
            assert app.coordination_access.service.root == second
        assert not ui.shows("OLD-WIRE-ONLY")


async def test_a_fresh_connection_after_a_flip_paints_only_the_newly_published_wire_and_keeps_rejected_drafts_editable(
        workspace, monkeypatch):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView

    attempt = workspace.roots.attempt
    home = select_root_by_default_route(monkeypatch, attempt)
    first, first_id = private_root(attempt / "first", workspace.project, "OLD-WIRE-ONLY")
    second, second_id = private_root(attempt / "second", workspace.project, "NEW-WIRE-ONLY")
    route_path = publish_route(home, first, first_id)

    # The same process first shows the former wire, then the route flips and that app closes.
    async with workspace.app(size=(115, 38)) as ui:
        await ui.open_channel("#team", actor="user")
        await ui.until_shows("OLD-WIRE-ONLY")
        publish_route(home, second, second_id)
        await ui.until(lambda: ui.textual[0].coordination_access.service.root == second, why="the app to follow the route")

    async with workspace.app(size=(115, 38)) as ui:
        app = ui.textual[0]
        assert app.coordination_access.service.root == second
        await ui.open_channel("#team", actor="user")
        view = app.screen.query_one(CommsChatView)
        await refresh_chat(view)
        await ui.step()
        assert view.display and view.message_history.source.comms.root == second
        assert any("NEW-WIRE-ONLY" in str(message) for message in view.message_history.messages), view.message_history.messages
        assert all("OLD-WIRE-ONLY" not in str(message) for message in view.message_history.messages)

        # A proven pre-append rejection remains editable; an UNKNOWN or an interrupted
        # committed send does not.
        with patch.object(view.message_history.source.comms.messaging, "send_user_message",
                          side_effect=ValueError("pre-append rejection")) as rejected:
            await view.submit_input(input_events.UserInputSubmitted("EDITABLE-REJECTION"))
            assert rejected.call_count == 1
            assert view.prompt.text == "EDITABLE-REJECTION"
            assert not view.prompt.prompt_text_area.disabled
            assert not view._send_block_reason
        view.prompt.text = ""

        # A send Core refuses to retry retains text for inspection and disables compose.
        error = HumanClaimBlockedError("prior reservation cannot be retried")
        with patch.object(view.message_history.source.comms.messaging, "send_user_message",
                          side_effect=error) as sender:
            event = input_events.UserInputSubmitted("BLOCKED-NO-RETRY")
            await view.submit_input(event)
            assert sender.call_count == 1
            assert view.send_block_reason == "Send blocked: prior reservation cannot be retried"
            assert view.prompt.text == event.body
            assert view.prompt.prompt_text_area.disabled
            await view.submit_input(event)
            assert sender.call_count == 1
        route_path.write_text("{")
        route_path.chmod(0o600)
        await refresh_chat(view)
        await ui.step()
        assert not view.display
        assert not ui.shows("NEW-WIRE-ONLY")
