"""Installed Toad/ACP/owner/Pi path with a loopback-only model fixture."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import DirectTarget, channel_target

from toad.thread_actions import StartAction
import asyncio
import json
import os
import shlex
import sys
import tempfile
import threading
import time
import psutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.native_package import verify_native_package
from agent_comms.threads import Thread
from agent_comms.input_disposition import InputDispositions
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.widgets.agent_response import AgentResponse
from toad.widgets.prompt import QueueSummary
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar
from toad import messages
from toad.navigation_preparation import ThreadNavigationRequest


def response_painted(app, view, text):
    window = view.window.region
    frame = "\n".join(strip.crop(window.x, window.right).text
                      for strip in app.screen._compositor.render_strips()[window.y:window.bottom])
    return text in frame and any(
        block in app.screen._compositor.visible_widgets and block.region.overlaps(window)
        for block in view.query(AgentResponse) if text in block.source
    )


async def until(pilot, predicate, seconds=20):
    async with asyncio.timeout(seconds):
        while not predicate():
            await pilot.pause(0.05)


async def notification_feedback(
    pilot, app, comms, owner_mode, project, entered, release, hold_next
):
    user = comms.messaging.user_identity(str(project)).name
    await channel_target("#team").open(NavigationContext(app, owner_mode, project, user))
    channel = app.screen.query_one(CommsChatView)
    entered.clear()
    release.clear()
    hold_next.set()
    await channel.submit_input(messages.UserInputSubmitted("CHANNEL_NATIVE_TRIAGE"))
    await until(pilot, entered.is_set)
    await until(pilot, lambda: comms.registry.require("beta").executing)
    await channel._refresh()
    await pilot.pause()
    roster = channel.query_one(ChannelParticipants)
    assert "beta" in roster.names.render().plain, roster.names.render()
    assert roster in app.screen._compositor.visible_widgets
    print("CHANNEL_ACTIVE_STATUS", roster.names.render().plain, flush=True)
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    await channel._refresh()
    await until(pilot, lambda: "No active turns" in roster.names.render().plain)
    assert "No active turns" in roster.names.render().plain, roster.names.render()
    print("CHANNEL_IDLE_STATUS_CONFIRMED", flush=True)
    notification = channel.query_one(MessageNotifications)
    try:
        await until(pilot, lambda: "Checked" in str(notification.title), 5)
        assert "no response" in str(notification.title).lower(), notification.title
    except TimeoutError, AssertionError:
        detail = {
            "title": str(notification.title),
            "details": str(notification.details.render()),
            "history": [(m.seq, m.body) for m, _ in channel._history],
            "visible": [m.seq for m, _ in channel._visible_notification_rows()],
        }
        try:
            detail["core"] = repr(
                comms.views.message_notifications(tuple(m for m, _ in channel._history))
            )
        except Exception as error:
            detail["coreError"] = repr(error)
        print("NOTIFICATION_FAILURE", json.dumps(detail), flush=True)
        raise
    print("CHANNEL_NOTIFICATION", str(notification.title), flush=True)


async def main(*, notification_only=False, retire_surface=False, app_type=ToadApp,
               acceptance=None, provider_reply=None, provider_usage=None,
               native_settings=None, prepare_state=None):
    evidence = Path(os.environ.get("L0A_EVIDENCE", os.environ["TMPDIR"]))
    evidence.mkdir(parents=True, exist_ok=True)
    package = Path(os.environ["AC_NATIVE_COPIED_PACKAGE"])
    verify_native_package(package)
    requests, failures = [], []
    entered, release, hold_next = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    hold_next.set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                request = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                requests.append(request)
                assert request["model"] == "fixture"
                assert self.headers["Authorization"] == "Bearer offline-only-fixture"
                assert len(requests) <= 12, "Unbounded model loop"
                if hold_next.is_set():
                    hold_next.clear()
                    entered.set()
                    assert release.wait(20), "UI did not release first response"
                content = "NATIVE_RESPONSE_" + str(len(requests))
                if any(
                    "IGNORE" in str(m.get("content"))
                    and "FULL" in str(m.get("content"))
                    for m in request["messages"]
                ):
                    content = '{"decision":"IGNORE"}'
                chunk = {
                    "id": "offline",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture",
                    "choices": [
                        {
                            "index": 0,
                            "delta": (provider_reply(request, len(requests))[0] if provider_reply
                                      else {"role": "assistant", "content": content}),
                            "finish_reason": None,
                        }
                    ],
                }
                final = {
                    **chunk,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": provider_reply(request, len(requests))[1] if provider_reply else "stop"}],
                    "usage": (provider_usage(request, len(requests)) if provider_usage else {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "total_tokens": 110,
                    }),
                }
                body = (
                    "".join(
                        "data: " + json.dumps(row) + "\n\n" for row in (chunk, final)
                    )
                    + "data: [DONE]\n\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as error:
                failures.append(str(error))
                print("LOOPBACK_PROVIDER_FAILURE", repr(error), flush=True)
                self.send_error(400, "Offline fixture failed")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    # Core private-root validation currently requires /var/tmp. Only disposable
    # wire data goes here; project/code/config/candidate wheels remain under ~/wt.
    with (
        tempfile.TemporaryDirectory(
            prefix="comms-l0a-native-", dir="/var/tmp"
        ) as wire_dir,
        tempfile.TemporaryDirectory(
            prefix="l0a-native-", dir=os.environ["TMPDIR"]
        ) as stage_dir,
    ):
        stage = Path(stage_dir)
        project = stage / "project"
        project.mkdir()
        config = stage / "pi"
        config.mkdir(mode=0o700)
        (config / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "selected-offline": {
                            "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                            "api": "openai-completions",
                            "models": [
                                {
                                    "id": "fixture",
                                    "name": "Offline fixture",
                                    "contextWindow": 32768,
                                    "maxTokens": 2048,
                                }
                            ],
                        }
                    }
                }
            )
        )
        if native_settings is not None:
            (config / "settings.json").write_text(json.dumps(native_settings))
        (config / "auth.json").write_text(
            json.dumps(
                {"selected-offline": {"type": "api_key", "key": "offline-only-fixture"}}
            )
        )
        comms = Comms(Path(wire_dir) / "wire")
        root_id = comms.messaging.initialize_private_initial_protocol()
        comms.threads.register(
            Thread(
                "beta",
                frozenset({"team"}),
                str(project),
                model="selected-offline/fixture",
                thinking_level="off",
            )
        )
        os.environ.update(
            AGENT_COMMS_ROOT=str(comms.root),
            AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
            AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
            PI_CODING_AGENT_DIR=str(config),
            AGENT_COMMS_AGENT_BIN="pi",
            AGENT_COMMS_AGENT_ARGS="--provider selected-offline --model fixture --no-extensions --no-skills --no-context-files",
            AGENT_COMMS_AGENT_MODELS="selected-offline/fixture",
            XDG_CONFIG_HOME=str(stage / "config"),
            XDG_DATA_HOME=str(stage / "data"),
            XDG_STATE_HOME=str(stage / "state"),
            AGENT_COMMS_DEBUG_LOG=str(stage / "acp-debug"),
        )
        for key in ("PI_PROMPT", "PI_PARENT_ID", "PI_AGENT_ID"):
            os.environ.pop(key, None)
        data = {
            "name": "Native fixture",
            "identity": "native-fixture",
            "short_name": "native",
            "protocol": "acp",
            "run_command": {"*": shlex.join([sys.executable, "-m", "agent_comms.acp"])},
        }
        if prepare_state is not None:
            await prepare_state(comms, project, requests, entered, release, hold_next)
        app = app_type(agent_data=data, project_dir=str(project), agent_session_id="beta")
        agent = None
        try:
            print("INSTALLED_APP_RUN_TEST_ENTER", flush=True)
            async with app.run_test(size=(160, 44)) as pilot:
                print("INSTALLED_APP_RUN_TEST_YIELDED", flush=True)
                await pilot.pause()
                owner_mode = app.selected_mode
                view = app.selected_session.conversation
                await until(pilot, lambda: view.agent is not None)
                agent = view.agent
                await until(pilot, agent.session_ready_event.is_set)
                assert agent._connected_ok, "Actual ACP attach failed"
                owner = comms.registry.require("beta")
                assert owner.process_identity is not None and owner.process_alive
                navigation = await asyncio.to_thread(
                    ThreadNavigationRequest(str(comms.root), "beta", project, ()).read
                )
                assert navigation.attachable and navigation.thread.process_alive
                print("ATTACHED_AND_NAVIGABLE", flush=True)
                if acceptance is not None:
                    await acceptance(app, pilot, agent, comms, entered, release,
                                     hold_next, requests)
                    assert not failures, failures
                    assert app._exception is None
                    return
                if notification_only:
                    await notification_feedback(
                        pilot,
                        app,
                        comms,
                        owner_mode,
                        project,
                        entered,
                        release,
                        hold_next,
                    )
                    assert len(requests) == 1, requests
                    assert not failures, failures
                    assert app._exception is None
                    print(
                        "PASS: installed native notification feedback; one loopback request",
                        flush=True,
                    )
                    return
                view.prompt.text = "FIRST_NATIVE_INPUT"
                await until(pilot, lambda: view.agent_ready)
                view.prompt.prompt_text_area.focus()
                await pilot.press("enter")
                await until(pilot, entered.is_set)
                print("PROVIDER_FIRST", flush=True)
                # An actual detached owner's turn is the status authority.
                # UI-only state changes cannot clear its busy witness; geometry
                # remains compact at both widths while the loopback holds it.
                sidebar = app.screen.query_one(CommsSidebar)
                sidebar._refresh()
                await until(pilot, lambda: any(row.target_name == "beta" and row.has_class("-busy")
                                              for row in sidebar.query(CommsRow)))
                app.session_tracker.update_session(owner_mode, state="idle", summary="Ready from the view")
                for width in (96, 120):
                    await pilot.resize_terminal(width, 44)
                    await pilot.pause()
                    sidebar._refresh()
                    await pilot.pause()
                    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
                    assert row.has_class("-busy") and row.region.height == 2, (row.render(), row.region)
                    assert "Ready from the view" not in row.render().plain
                    assert "provider/" not in row.render().plain
                await pilot.resize_terminal(160, 44)
                print("NATIVE_SIDEBAR_BUSY_AUTHORITY_CONFIRMED", flush=True)
                view.prompt.text = "unsent local draft"
                retired_editor = None
                if retire_surface:
                    retired_editor = view.prompt.prompt_text_area.capture_editor_state()
                    parent = view.parent
                    process = agent.process.process
                    original_queue = agent.queue_attachment
                    agent.detach_surface(view)
                    await view.remove()
                    assert agent.process.process is process and process.returncode is None
                    assert agent.controller.surface.target is None
                await asyncio.wait_for(
                    agent.send_prompt("QUEUED_NATIVE_INPUT", defer_display=True), 10
                )
                if retire_surface:
                    await until(pilot, lambda: bool(agent.queue_attachment.projection.items))
                    from toad.widgets.conversation import Conversation
                    replacement = Conversation(project)
                    await parent.mount(replacement)
                    replacement.prompt.prompt_text_area.restore_editor_state(retired_editor)
                    replacement.agent = agent
                    view = replacement
                    await until(pilot, lambda: view.turns.managed_id == agent._active_turn_id)
                    await until(pilot, lambda: view.current_model is not None)
                    assert view.current_model.id == "selected-offline/fixture"
                    assert view.busy_count == 1
                    assert agent.queue_attachment is original_queue
                    assert agent.process.process is process and process.returncode is None
                    print("RETIRED_SURFACE_NATIVE_QUEUE_REBOUND", flush=True)
                await until(pilot, lambda: bool(view.queue_projection.items))
                queued_ids = [row.input_id for row in view.queue_projection.items]
                assert len(queued_ids) == 1
                assert (
                    "QUEUED_NATIVE_INPUT" in view.query_one(QueueSummary).render().plain
                )
                print("QUEUED", queued_ids, flush=True)
                release.set()
                await until(pilot, lambda: agent.presentation.prompt_in_flight == 0, 25)
                await until(pilot, lambda: not comms.registry.require("beta").executing)
                await pilot.pause()
                assert len(requests) >= 2, "Queued native input never reached provider"
                assert not view.queue_projection.items
                assert view.prompt.text == "unsent local draft"
                await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_2"))
                print("ACTUAL_LIVE_AND_SAVED_RESPONSE_PAINT_CONFIRMED", flush=True)
                # Real native source read, evidence-backed live-to-saved publication.
                from toad.widgets.transcript_history import TranscriptHistory
                await until(pilot, lambda: view.turns.managed_id is None)
                await until(pilot, lambda: all(history.checkpoint_available for history in view.contents.query(TranscriptHistory)))
                view.window.anchor()
                view.transcript.require_checkpoint()
                await until(pilot, lambda: not view.transcript.dirty)
                await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_2"))
                assert view.contents.query(TranscriptHistory)
                assert not any(isinstance(child, AgentResponse) for child in view.contents.children)
                assert view.transcript.displayed_cursor is not None
                print("ACTUAL_NATIVE_CHECKPOINT_SOURCE_AND_PAINT_CONFIRMED", flush=True)
                print("NATIVE_QUEUE_DONE", len(requests), flush=True)
                print("QUEUE_PROJECTION", view.queue_projection, flush=True)
                print(
                    "INPUT_DELIVERY",
                    json.dumps(view.input_delivery, default=str),
                    flush=True,
                )
                native_file = Path(comms.registry.require("beta").session_file)
                native_rows = [
                    json.loads(line) for line in native_file.read_text().splitlines()
                ]
                disposition = (
                    InputDispositions(comms.root / InputDispositions.filename)
                    .read()
                    .rows["acp:" + queued_ids[0]]
                )
                (evidence / "native-session.jsonl").write_text(
                    native_file.read_text()
                )
                print(
                    "NATIVE_MAPPING", queued_ids[0], disposition.native_id, flush=True
                )
                assert any(
                    row.get("message", {}).get("inputId") == disposition.native_id
                    for row in native_rows
                )
                assert not disposition.unresolved
                print("NATIVE_CONSUMPTION_CONFIRMED", flush=True)

                # Cold ACP client attaches to the same detached owner and saved
                # transcript; attachment must not produce another model request.
                native_count = len(requests)
                old_process = comms.registry.require("beta").process_identity
                original_watcher = view._directory_watcher
                assert original_watcher is not None
                await agent.reconnect()
                await until(pilot, agent.session_ready_event.is_set)
                assert agent._connected_ok
                await until(
                    pilot,
                    lambda: response_painted(app, view, "NATIVE_RESPONSE_2"),
                )
                assert comms.registry.require("beta").process_identity == old_process
                assert len(requests) == native_count
                await until(pilot, lambda: view.queue_projection.status == "available")
                assert not view.queue_projection.items
                await pilot.pause()
                assert view._directory_watcher is original_watcher
                print("COLD_REATTACH_CONFIRMED", flush=True)

                user = comms.messaging.user_identity(str(project)).name
                await DirectTarget("beta").open(NavigationContext(app, owner_mode, project, user))
                dm = app.screen.query_one(CommsChatView)
                entered.clear()
                release.clear()
                hold_next.set()
                await dm.submit_input(
                    messages.UserInputSubmitted("DIRECT_NATIVE_MESSAGE")
                )
                await until(pilot, entered.is_set)
                assert comms.registry.require("beta").executing
                release.set()
                await until(
                    pilot,
                    lambda: any(
                        row.sender == "beta" and row.body.startswith("NATIVE_RESPONSE_")
                        for row, _ in dm._history
                    ),
                )
                await until(pilot, lambda: not comms.registry.require("beta").executing)
                print("DM_NATIVE_REPLY_CONFIRMED", flush=True)

                await notification_feedback(
                    pilot, app, comms, owner_mode, project, entered, release, hold_next
                )

                # A stopped owner's saved native session must reopen through
                # the same installed entrypoint and accept a new native input.
                proxy_process = agent.process.process
                await agent.stop()
                assert proxy_process.returncode is not None
                assert not agent.permissions.pending
                print("ACTUAL_ACP_PROCESS_CLEANUP_CONFIRMED", flush=True)
                await asyncio.to_thread(comms.owners.stop, "beta")
                assert not comms.registry.require("beta").process_alive
                app.thread_actions.invoke(StartAction(), "beta", user)
                await until(pilot, lambda: "beta" not in app.thread_actions.pending)
                assert comms.registry.require("beta").process_alive, (
                    "Explicit Start did not launch owner"
                )
                before_restart = len(requests)
                await app.select_session(owner_mode)
                view = app.selected_session.conversation
                assert view.agent is agent, "Returning to a session replaced its operational owner"
                await agent.reconnect()
                await until(pilot, agent.session_ready_event.is_set)
                assert agent._connected_ok, "Stopped native owner failed to reopen"
                try:
                    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_2"))
                except TimeoutError:
                    region = view.window.region
                    print("REOPEN_PAINT_FAILURE", json.dumps({
                        "ready": view.agent_ready,
                        "surface_matches": agent.controller.surface.target is view,
                        "view_region": repr(view.region), "window_region": repr(region),
                        "blocks": [(type(block).__name__, repr(block.region), block.display)
                                   for block in view.contents.walk_children()],
                        "paint": "\n".join(strip.crop(region.x, region.right).text for strip in
                            app.screen._compositor.render_strips()[region.y:region.bottom]),
                    }), flush=True)
                    raise
                assert len(requests) == before_restart, "Restart replayed a model input"
                restarted = comms.registry.require("beta").process_identity
                assert restarted is not None and restarted != old_process
                await asyncio.wait_for(agent.send_prompt("AFTER_RESTART_NATIVE"), 20)
                await until(pilot, lambda: not comms.registry.require("beta").executing)
                assert len(requests) == before_restart + 1
                print("STOPPED_OWNER_NATIVE_REOPEN_CONFIRMED", flush=True)
                # Observe a quiescent installed owner and mounted UI: no model
                # request or turn is permitted without a new input.
                before = len(requests)
                process = psutil.Process(restarted.pid)
                cpu_before = sum(process.cpu_times()[:2])
                ui_process = psutil.Process()
                ui_cpu_before = sum(ui_process.cpu_times()[:2])
                clock_before = time.monotonic()
                await pilot.pause(2)
                idle_cpu = sum(process.cpu_times()[:2]) - cpu_before
                assert len(requests) == before
                assert not comms.registry.require("beta").executing
                print(
                    "IDLE",
                    json.dumps(
                        {
                            "seconds": time.monotonic() - clock_before,
                            "ownerCpuSeconds": idle_cpu,
                            "uiCpuSeconds": sum(ui_process.cpu_times()[:2])
                            - ui_cpu_before,
                            "modelRequests": len(requests) - before,
                        }
                    ),
                    flush=True,
                )
                assert not failures, failures
                assert app._exception is None
        finally:
            for path in (comms.root / "diagnostics").glob("owner-*.log"):
                (evidence / path.name).write_bytes(path.read_bytes())
            release.set()
            if agent:
                await agent.stop()
                if agent.presentation.log_path.exists():
                    (evidence / "toad-acp.log").write_bytes(
                        agent.presentation.log_path.read_bytes()
                    )
            for path in (stage / "state" / "toad" / "logs").glob("*.txt"):
                (evidence / path.name).write_bytes(path.read_bytes())
            for path in stage.glob("acp-debug*"):
                destination = evidence / path.name
                destination.write_bytes(path.read_bytes())
            await asyncio.to_thread(comms.owners.stop, "beta")
            server.shutdown()
            server.server_close()
    print("PASS: installed actual native queue path; loopback model only", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notification-only", action="store_true")
    parser.add_argument("--retire-surface", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(notification_only=args.notification_only, retire_surface=args.retire_surface))
