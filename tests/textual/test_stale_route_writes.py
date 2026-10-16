"""Textual-facing: mounted view writes (read marks, thread actions) started before a route publication are refused after it."""

import asyncio
import os
import threading

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from agent_comms import private_nk_entrypoint
from agent_comms.active_route import ActiveRoute, publish_active_route
from agent_comms.cli_commands import StartCliCommand
from agent_comms.comms import Comms
from agent_comms.route_selection import current_root, run_selected_write
from agent_comms.thread_identity import ThreadRole
from agent_comms.threads import Thread

from support.routes import private_root, select_root_by_default_route
from support.textual_steps import refresh_chat, request_target_command


async def test_delayed_view_writes_wait_out_a_route_publication_and_are_then_refused(workspace, monkeypatch, native_package):
    from toad import comms_root
    from toad.acp.shell_command import ShellCommand
    from toad.widgets.comms_chat import CommsChatView
    from agent_comms.acp_ingress import AcpIngress
    from agent_comms.route_selection import RouteSelection

    attempt = workspace.roots.attempt
    project = workspace.project
    home = select_root_by_default_route(monkeypatch, attempt)
    legacy = home / ".agent-comms"
    legacy.mkdir(mode=0o700)
    old = Comms(legacy)
    old.registry.declare(Thread("user", frozenset(), str(project), role=ThreadRole.USER))
    old.registry.declare(Thread("peer", frozenset({"team"}), str(project / "peer")))
    old.messaging.send("peer", "#team", "LEGACY-PAINT")
    private, private_id = private_root(attempt / "private", project, "PRIVATE-PAINT")
    route = ActiveRoute(private, private_id, native_package)
    assert current_root() == legacy

    async with workspace.app(size=(115, 38)) as ui:
        app = ui.textual[0]
        await ui.open_channel("#team", actor="user")
        view = app.screen.query_one(CommsChatView)
        await refresh_chat(view)
        await ui.step()
        assert view.message_history.source.comms.root == legacy
        old.messaging.send("peer", "#team", "UNREAD-OLD")
        page = old.views.channel_display_page("#team", worktree=str(project), limit=8)
        assert page.newest_seq == 2
        marker = legacy / "read_markers.json"
        before = marker.read_bytes() if marker.exists() else b""

        entered_ack, entered_action = asyncio.Event(), threading.Event()
        release = threading.Event()
        original_to_thread = asyncio.to_thread
        real_write = comms_root.run_selected_write
        invoked = []

        async def delayed_dispatch(operation, *args, **kwargs):
            if operation is run_selected_write and getattr(args[1], "__name__", "") == "mark_channel_view_read":
                entered_ack.set()
                await original_to_thread(release.wait, 20)
            return await original_to_thread(operation, *args, **kwargs)

        def delayed_write(root, operation, *args, **kwargs):
            entered_action.set()
            release.wait(20)
            return real_write(root, operation, *args, **kwargs)

        def safe_spy(command, comms):
            invoked.append(command.name)
            return {"thread": command.name, "pid": 0, "launched": False}

        with (patch("asyncio.to_thread", delayed_dispatch),
              patch.object(comms_root, "run_selected_write", delayed_write),
              patch.object(StartCliCommand, "apply", safe_spy),
              patch.object(private_nk_entrypoint, "_trusted_package", lambda _: None)):
            history = view.message_history
            ack = asyncio.create_task(history.mark_page(page, None, snapshot=history.source_snapshot()))
            request_target_command(app, StartCliCommand, "peer")
            async with asyncio.timeout(8):
                while not (entered_ack.is_set() and entered_action.is_set()):
                    await original_to_thread(entered_action.wait, 0.05)
                    await asyncio.sleep(0)
            # An in-flight ACP spawn holds the route's shared lock through process settlement,
            # so publication cannot pass it; the delayed view writes have not taken that lock yet.
            spawn_entered, release_spawn = asyncio.Event(), asyncio.Event()

            async def fake_spawn(_command, **_kwargs):
                spawn_entered.set()
                await release_spawn.wait()
                return SimpleNamespace(pid=123, returncode=0)

            with patch("agent_comms.child_process.AttachedChild.start", fake_spawn):
                env = dict(os.environ)
                selection = RouteSelection.for_child(env, project)
                spawn = asyncio.create_task(AcpIngress(selection, project).spawn(
                    ShellCommand.current().argv("fake"), env=env))
                async with asyncio.timeout(8):
                    await spawn_entered.wait()
                publish = asyncio.get_running_loop().run_in_executor(None, publish_active_route, route)
                await asyncio.sleep(0.2)
                assert not publish.done()
                release_spawn.set()
                await spawn
                async with asyncio.timeout(5):
                    await asyncio.shield(publish)
            assert current_root() == private
            release.set()
            await ack
            await ui.step()
        assert not invoked, "stale old-root start reached its core operation"
        assert (marker.read_bytes() if marker.exists() else b"") == before
        with pytest.raises(ValueError):
            run_selected_write(legacy, safe_spy, None, None, implicit=True)
