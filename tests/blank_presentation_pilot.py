"""Actual retained editors and session-owned shells survive physical tab returns."""

import asyncio
import sys
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from native_session_retention_pilot import conversation_paint
from textual.widgets.text_area import Selection

from toad.widgets.conversation import Conversation
from toad.widgets.prompt import PromptTextArea
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.side_bar import SideBar
from toad.screens.main import MainScreen
from toad.shell_output import ShellTerminalOutput
from toad.widgets.shell_result import ShellResult
from toad.core.input_events import UserInputSubmitted


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def select(app, pilot, source):
    label = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(label)
    await pilot.pause()
    assert app.selected_session is source


async def layout_preferences():
    """The original App/settings/tab path must paint original preferences."""
    from toad.preferences import ToadSettings, UiSettings
    from toad.setting_choices import HiddenScrollbar, NormalScrollbar, ThinScrollbar
    from toad.setting_widgets import InputEditor, ChoiceEditor
    from toad.screens.settings import SettingsScreen

    with TemporaryDirectory(prefix="toad-layout-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        settings = ToadSettings(json.loads(Path(__file__).with_name("fixtures").joinpath("saved-settings.json").read_text()))
        settings.ui.column = True
        settings.ui.column_width = 60
        settings.ui.scrollbar = ThinScrollbar
        path = root / "config" / "toad" / "toad.json"
        path.parent.mkdir(parents=True)
        path.write_text(settings.json)
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            first = app.selected_session
            first.conversation.prompt.text = "retained layout draft"
            assert first.conversation.styles.max_width.value == 60
            assert first.conversation.has_class("-scrollbar-thin")
            assert first.conversation.window.scrollbar_size_vertical == 1
            await app.session_navigation.new(app.session_navigation.default_source)
            second = app.selected_session
            await pilot.pause()
            assert second.conversation.styles.max_width.value == 60
            assert second.conversation.has_class("-scrollbar-thin")
            await app.push_screen(SettingsScreen())
            await pilot.pause()
            async with asyncio.timeout(8):
                while not any(w.bound.kind is UiSettings.column_width for w in app.screen.query(InputEditor)):
                    await pilot.pause(.05)
            width = next(w for w in app.screen.query(InputEditor) if w.bound.kind is UiSettings.column_width)
            width.value = "74"
            width.focus()
            await pilot.pause()
            await pilot.press("tab")
            choice = next(w for w in app.screen.query(ChoiceEditor) if w.bound.kind is UiSettings.scrollbar)
            choice.value = HiddenScrollbar
            await pilot.pause()
            for view in (first, second):
                assert view.conversation.styles.max_width.value == 74
                assert view.conversation.has_class("-scrollbar-hidden")
                assert not view.conversation.has_class("-scrollbar-thin")
            await app.pop_screen()
            await select(app, pilot, first)
            assert first.conversation.prompt.text == "retained layout draft"
            assert first.conversation.window.scrollbar_size_vertical == 0
            await app.session_navigation.new(first.spawn)
            peer = app.selected_session
            await pilot.pause()
            assert peer.conversation.styles.max_width.value == 74
            assert peer.conversation.has_class("-scrollbar-hidden")
            app.settings.ui.column = False
            app.settings.ui.scrollbar = NormalScrollbar
            await pilot.pause()
            for view in (first, second, peer):
                assert view.conversation.styles.max_width is None
                assert view.conversation.has_class("-scrollbar-normal")
                assert not view.conversation.has_class("-scrollbar-hidden")
            assert peer.conversation.window.scrollbar_size_vertical == 2
            await app.settings.save()
            reopened = ToadSettings(json.loads(path.read_text()))
            assert reopened.ui.column is False and reopened.ui.column_width == 74
            assert reopened.ui.scrollbar is NormalScrollbar
            evidence = Path(os.environ["TOAD_LAYOUT_EVIDENCE"])
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(str(evidence / "layout.svg"))
            (evidence / "receipt.json").write_text(json.dumps({
                "result": "pass", "installed_toad": __import__("toad").__file__,
                "saved_preferences_initial_paint": True,
                "settings_modal_updates_visible_and_parked_views": True,
                "physical_tab_return_retains_original_draft": True,
                "peer_spawn_reads_current_preferences": True,
                "native_width_and_scrollbar_paint": True,
                "save_reopen_original_values": True,
                "providers": 0, "native_inputs": 0,
                "scope": "Installed original App/Pilot/settings/tab/native CSS; no physical st or ACP socket/provider/performance claim",
            }, indent=2) + "\n")
    print("PASS original settings -> mounted/parked/new chat layout; native CSS; tab draft; save/reopen", flush=True)


async def danger_projection():
    """Unsent shell draft paints original command analysis through the App."""
    from toad.danger import analyze
    with TemporaryDirectory(prefix="toad-danger-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            first = app.selected_session
            prompt = first.conversation.prompt
            prompt.shell_mode = True
            command = "rm ../outside; echo safe; rm local"
            prompt.text = command
            await pilot.pause()
            editor = prompt.prompt_text_area
            styles = tuple(span.style for span in editor.highlight_shell(command).spans)
            warning = "$text-error on $error-muted 70%"
            assert warning in styles
            atoms = analyze(str(project), str(project), command)
            assert analyze(str(project), str(project), command) is atoms
            assert any(span.style == warning for line in editor.highlight_lines for span in line.spans)
            evidence = Path(os.environ["TOAD_DANGER_EVIDENCE"])
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(str(evidence / "danger-draft.svg"))
            await app.session_navigation.new(app.session_navigation.default_source)
            await pilot.pause()
            await select(app, pilot, first)
            assert first.conversation.prompt is prompt and prompt.text == command
            app.settings.shell.warn_dangerous = False
            assert warning not in tuple(span.style for span in editor.highlight_shell(command).spans)
            app.settings.shell.warn_dangerous = True
            assert warning in tuple(span.style for span in editor.highlight_shell(command).spans)
            assert analyze(str(project), str(project), command) is atoms
            assert app._exception is None
            (evidence / "receipt.json").write_text(json.dumps({
                "result": "pass", "installed_toad": __import__("toad").__file__,
                "unsent_draft": command, "native_warning_spans": True,
                "physical_pilot_tab_return_retains_draft": True,
                "original_setting_controls_native_projection": True,
                "one_bounded_analysis_cache": True, "inputs": 0, "providers": 0,
                "scope": "Installed actual App/Pilot/editor/native highlight; no shell execution or physical st/performance claim",
            }, indent=2) + "\n")
    print("PASS installed original App unsent shell warning / retained tab / original setting", flush=True)


async def response_projection():
    """Original response routes/categories become native headers in the App."""
    from agent_comms.routing import MessageRoute
    from toad.live_output import ResponseStream
    from toad.response_delivery import RoutedResponse
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.message_divider import MessageDivider, RecordedMessageClock
    from toad.widgets.message_filter import AgentCategory, OutboundCategory, OtherCategory
    from toad.widgets.route_header import RouteHeader

    with TemporaryDirectory(prefix="toad-response-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            ordinary = await view.output.append(ResponseStream(), "ordinary response body")
            await view.output.finish(ResponseStream)
            route = MessageRoute("owner", ("#response-scope",))
            delivery = RoutedResponse(route)
            clock = RecordedMessageClock(1790998422.196897)
            routed = await view.post(AgentResponse("routed response body", delivery=delivery,
                                                 clock=clock))
            hidden = await view.post(AgentResponse("hidden-divider response body", delivery=delivery,
                                                 category=OtherCategory, show_divider=False))
            await pilot.pause()
            assert ordinary.message_category is AgentCategory
            assert ordinary.has_class("block") and not ordinary.has_class("-routed")
            assert len(ordinary.query(MessageDivider)) == 1
            assert ordinary.query_one(MessageDivider).label == "Agent"
            assert routed.delivery is delivery and routed.message_category is OutboundCategory
            assert routed.has_class("block") and routed.has_class("-routed")
            assert len(routed.query(MessageDivider)) == 1
            divider = routed.query_one(MessageDivider)
            assert divider.label == "Outbound" and divider.clock == clock.display()[0]
            assert routed.query_one(RouteHeader).route is route
            assert hidden.delivery is delivery and hidden.message_category is OtherCategory
            assert hidden.has_class("block") and hidden.has_class("-routed")
            assert not hidden.query(MessageDivider) and not hidden.query(RouteHeader)
            async with asyncio.timeout(8):
                while not all(text in conversation_paint(app.screen) for text in (
                    "ordinary response body", "routed response body", "hidden-divider response body",
                    "#response-scope", "Outbound",
                )):
                    await pilot.pause(.05)
            assert app._exception is None
            evidence = Path(os.environ["TOAD_RESPONSE_EVIDENCE"])
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(str(evidence / "responses.svg"))
            (evidence / "receipt.json").write_text(json.dumps({
                "result": "pass", "installed_toad": __import__("toad").__file__,
                "original_live_stream_agent_header": True,
                "original_route_identity_native_header": True,
                "recorded_clock_and_default_block_class": True,
                "hidden_divider_keeps_routed_style_and_explicit_category": True,
                "actual_composited_response_bodies_and_header": True,
                "inputs": 0, "providers": 0,
                "scope": "Actual installed App/Pilot/native response paint; no ACP/provider/physical st/performance claim",
            }, indent=2) + "\n")
    print("PASS installed response route/header/category/style/native body projection", flush=True)


async def frame_admission():
    """Real App frames retain hidden work and keep pending source I/O off Screen."""
    from textual.screen import Screen

    with TemporaryDirectory(prefix="toad-frame-admission-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first = app.selected_session
            window = first.conversation.window
            frame = app.workspace_screen.frame_presentation
            await app.session_navigation.new(app.session_navigation.default_source)
            await pilot.pause()

            hidden = asyncio.Event()
            frame.defer(window, hidden.set)
            refreshed = asyncio.Event()
            app.workspace_screen.call_after_refresh(refreshed.set)
            app.workspace_screen.refresh()
            async with asyncio.timeout(5):
                await refreshed.wait()
            assert not hidden.is_set() and (window, hidden.set) in frame.callbacks
            await app.select_session(first.id)
            async with asyncio.timeout(5):
                await hidden.wait()
            assert (window, hidden.set) not in frame.callbacks

            entered, release, finished, painted = (asyncio.Event() for _ in range(4))

            async def pending_source():
                entered.set()
                try:
                    await release.wait()
                finally:
                    finished.set()

            editor = first.conversation.prompt.prompt_text_area
            frame.defer(window, pending_source)
            try:
                async with asyncio.timeout(5):
                    await entered.wait()
                editor.insert("frame while source pending")
                frame.defer(editor, painted.set)
                app.workspace_screen.refresh()
                # Pilot.pause waits on every widget pump, including the deliberately
                # pending source. Await the actual frame admission instead.
                async with asyncio.timeout(5):
                    await painted.wait()
                assert not finished.is_set() and not app._batch_count
                assert "frame while source pending" in "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips())
            finally:
                release.set()
                async with asyncio.timeout(5):
                    await finished.wait()

            modal = Screen()
            await app.push_screen(modal)
            await pilot.pause()
            inactive = asyncio.Event()
            frame.defer(window, inactive.set)
            modal_frame = asyncio.Event()
            modal.call_after_refresh(modal_frame.set)
            modal.refresh()
            async with asyncio.timeout(5):
                await modal_frame.wait()
            assert not inactive.is_set() and (window, inactive.set) in frame.callbacks
            await app.pop_screen()
            async with asyncio.timeout(5):
                await inactive.wait()
            assert (window, inactive.set) not in frame.callbacks
            assert app._exception is None
            evidence = Path(os.environ["TOAD_FRAME_EVIDENCE"])
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "receipt.json").write_text(json.dumps({
                "result": "pass", "installed_toad": __import__("toad").__file__,
                "hidden_source_retained_until_selected": True,
                "native_paint_during_pending_source_callback": True,
                "inactive_workspace_retained_until_return": True,
                "provider_calls": 0, "native_inputs": 0,
                "scope": "Original installed App, source selection and native compositor; synchronous test driver, no terminal writer or physical motion claim",
            }, indent=2) + "\n")
    print("PASS original frame/source admission; pending I/O leaves native paint free", flush=True)


async def startup_hydration():
    """Actual startup and mount work remain pending while their own pumps run."""
    from threading import Event
    from textual import events
    from textual.geometry import Size
    from unittest.mock import patch
    from agent_comms.threads import Thread
    from runtime_fixture import private_native_wire
    from toad.acp.maintenance_ingress import preflight
    from toad.screens.comms import CommsScreen
    from toad.widgets.comms_chat import CommsChatView
    from toad.conversation_kind import ChannelConversation
    from toad.session_admission import HistorySessionAdmission
    from toad.session_tracker import CommsViewKey

    with TemporaryDirectory(prefix="toad-start-hydrate-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = private_native_wire(root / "wire")
        comms.registry.declare(Thread("pump-owner", frozenset({"pump"}), str(root)))
        entered, release, finished = Event(), Event(), Event()

        def held_preflight(*args, **kwargs):
            entered.set()
            try:
                assert release.wait(5), "startup preflight control was not released"
                return preflight(*args, **kwargs)
            finally:
                finished.set()

        async def input_and_resize(owner, editor, text, size):
            app.screen.set_focus(editor, scroll_visible=False)
            # Use the original driver input path, without Pilot's global
            # all-pump barrier (the child mount is deliberately pending).
            await app._press_keys(text)
            pumped = asyncio.Event()
            owner.call_later(pumped.set)
            async with asyncio.timeout(5):
                await pumped.wait()
            requested = Size(*size)
            app._driver._size = requested
            app.post_message(events.Resize(requested, requested))
            async with asyncio.timeout(5):
                while app.screen.size != requested:
                    await app.screen.wait_for_refresh()
                await app.screen.wait_for_refresh()
            assert text in editor.text and owner.is_attached
            assert text in "\n".join(strip.text for strip in app.screen._compositor.render_strips())

        data = {"name": "Pending startup", "identity": "pending-startup", "short_name": "pending",
                "protocol": "acp", "run_command": {"*": "true"}}
        app = InstalledApp(agent_data=data, project_dir=str(root))
        with patch("toad.acp.maintenance_ingress.preflight", held_preflight):
            try:
                async with app.run_test(size=(100, 35)) as pilot:
                    async with asyncio.timeout(5):
                        await asyncio.to_thread(entered.wait)
                    first = app.selected_session
                    conversation = first.conversation
                    agent = conversation.agent
                    assert agent is not None and agent.process.responses
                    await input_and_resize(conversation, conversation.prompt.prompt_text_area,
                                           "startup-pump", (104, 36))
                    await app.session_navigation.new(lambda: MainScreen(root))
                    assert first.presentation.sources.agent is agent
                    assert agent.process.responses and agent.process.runner is None
                    await app.select_session(first.id)
                    assert first.conversation.agent is agent
                    assert conversation.prompt.text == "startup-pump"
                    await app.workspace_sessions.close(first.id)
                    assert not agent.process.responses and agent.process.runner is None
                    assert not agent.process.accepts_updates
                    assert app._exception is None
            finally:
                release.set()
                async with asyncio.timeout(5):
                    await asyncio.to_thread(finished.wait)

        mounted, continue_mount = asyncio.Event(), asyncio.Event()

        class HeldChat(CommsChatView):
            async def initialize_view(self):
                mounted.set()
                await continue_mount.wait()
                await super().initialize_view()

        def pending_chat(screen):
            return HeldChat(screen.project_path, me=screen.me, target=screen.target,
                            kind=screen.kind, wire_root=screen.wire_root)

        app = InstalledApp(project_dir=str(root))
        with patch.object(CommsScreen, "create_chat", pending_chat):
            async with app.run_test(size=(100, 35)) as pilot:
                await app.selected_session.wait_content_ready()
                first = app.selected_session
                key = CommsViewKey(str(comms.root), first.id, "pump-owner", ChannelConversation, "#pump")
                admission = HistorySessionAdmission("pending-hydration", key, ChannelConversation, root, None, ())
                opening = asyncio.create_task(app.session_navigation.admit(admission))
                try:
                    async with asyncio.timeout(5):
                        await mounted.wait()
                    view = app.workspace_sessions.require(admission.mode)
                    editor = view.query_one(PromptTextArea)
                    await input_and_resize(view, editor, "hydration-pump", (106, 37))
                    assert not opening.done() and not view._content_ready.is_set()
                    await app.select_session(first.id)
                    focused = app.screen.focused
                    continue_mount.set()
                    assert await opening == admission.mode
                    assert app.selected_session is first and app.screen.focused is focused
                    await app.select_session(view.id)
                    assert view.query_one(PromptTextArea) is editor and editor.text == "hydration-pump"
                    assert app._exception is None
                finally:
                    continue_mount.set()
                    await asyncio.gather(opening, return_exceptions=True)
        evidence = Path(os.environ["TOAD_STARTUP_EVIDENCE"])
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "receipt.json").write_text(json.dumps({
            "result": "pass", "installed_toad": __import__("toad").__file__,
            "startup_owner_pump_input_resize_while_preflight_pending": True,
            "startup_hidden_return_same_operational_owner": True,
            "close_revokes_pending_startup_without_runner": True,
            "hydration_owner_pump_input_resize_while_mount_pending": True,
            "hidden_hydration_preserves_selected_focus": True,
            "whole_app_close": True, "provider_calls": 0, "native_inputs": 0,
            "scope": "Original App, Agent/preflight, native mount/worker/input pumps and compositor; controlled pending work, no terminal movie or smoothness claim",
        }, indent=2) + "\n")
    print("PASS actual startup/hydration pumps, input, resize, hidden return and whole close", flush=True)


async def main():
    with TemporaryDirectory(prefix="toad-session-surface-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first = app.selected_session
            first_surface = first.conversation
            original_task = first_surface._task
            window = first_surface.window
            viewport = window.document_viewport
            assert window in first.viewport_presentation.windows
            editor = first.conversation.prompt.prompt_text_area
            editor.insert("first draft")
            editor.history.checkpoint()
            editor.insert(" and more")
            editor.selection = Selection((0, 1), (0, 5))
            await pilot.pause()
            expected = editor.text
            history = editor.history
            document = editor.document

            second_mode = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
            await pilot.pause()
            assert first.query_one(Conversation) is first_surface
            second = app.selected_session
            second_surface = second.conversation
            assert second_surface is not first_surface
            assert first_surface._task is original_task
            assert window in app.workspace_screen.viewport_presentation.windows and window.screen is app.workspace_screen
            second.conversation.prompt.text = "second draft"

            await select(app, pilot, first)
            await pilot.pause()
            restored = first.query_one(PromptTextArea)
            assert first.conversation is first_surface and first_surface._task is original_task
            assert window in app.workspace_screen.viewport_presentation.windows and window.screen is app.workspace_screen
            assert restored.text == expected
            assert restored.document is document and restored.history is history
            assert restored.selection == Selection((0, 1), (0, 5))
            restored.undo()
            assert restored.text == "first draft"
            restored.redo()
            assert restored.text == expected
            assert app.workspace_sessions.require(second_mode).conversation is second_surface
            await select(app, pilot, second)
            assert second.conversation is second_surface
            assert second.conversation.prompt.text == "second draft"
            await second.conversation.post_shell("sleep 1; printf 'owned-shell-marker\\n'")
            async with asyncio.timeout(5):
                while not second.conversation.query("ShellTerminal"):
                    await pilot.pause(.02)
            shell = second.conversation._shell
            assert shell.surface.target is second_surface
            assert len(shell.events.subscriptions) == 1
            shell_operation = shell._operation
            shell_custody = await shell_operation.custody()
            command_view = second_surface.query_one(ShellResult)
            terminal_view = shell.output.terminal
            async with asyncio.timeout(5):
                while not await shell.is_busy():
                    await pilot.pause(.02)
            await second.conversation.submit_input(UserInputSubmitted("busy-shell-input", shell=True))
            # Widget.focus publishes through App.call_later; direct PTY writes
            # no longer happen to await a separate executor first.
            await pilot.pause()
            assert app.focused is shell.output.terminal
            third = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
            assert second.query_one(Conversation) is second_surface
            assert second.presentation.sources.shell is shell
            assert shell._operation is shell_operation and not shell_operation.task.done()
            assert await shell._operation.custody() is shell_custody
            assert shell_custody.child.alive()
            assert shell.surface.target is None and not shell.events.subscriptions
            async with asyncio.timeout(5):
                while not any("owned-shell-marker" in "\n".join(line.content.plain for line in output.state.buffer.lines)
                              for output in shell.outputs if isinstance(output, ShellTerminalOutput)):
                    await pilot.pause(.02)
            assert all(output.terminal is None for output in shell.outputs
                       if isinstance(output, ShellTerminalOutput))
            await select(app, pilot, second)
            restored_shell_view = app.selected_session.conversation
            assert restored_shell_view is second_surface
            assert restored_shell_view._shell is shell
            assert shell.surface.target is restored_shell_view
            assert len(shell.events.subscriptions) == 1
            assert restored_shell_view.prompt.text == "second draft"
            assert tuple(restored_shell_view.query(ShellResult)) == (command_view,)
            assert any(output is command_view.source for output in shell.outputs)
            assert command_view.get_clipboard_text() == command_view.source.command
            assert terminal_view in restored_shell_view.query("ShellTerminal")
            assert any(output.terminal is terminal_view for output in shell.outputs
                       if isinstance(output, ShellTerminalOutput))
            assert any(terminal.state is output.state for terminal in restored_shell_view.query("ShellTerminal")
                       for output in shell.outputs if isinstance(output, ShellTerminalOutput))
            await pilot.pause()
            paint = conversation_paint(app.screen)
            assert "owned-shell-marker" in paint, paint
            # Read actual terminal pixels, excluding the command caption.
            terminal_paint = "\n".join(
                strip.crop(terminal.region.x, terminal.region.right).text
                for output in shell.outputs if isinstance(output, ShellTerminalOutput)
                for terminal in (output.terminal,) if terminal is not None
                for strip in app.screen._compositor.render_strips()[terminal.region.y:terminal.region.bottom]
            )
            assert "owned-shell-marker" in terminal_paint, terminal_paint
            shell_directory = root / "shell directory"
            shell_directory.mkdir()
            await shell.change_directory(str(shell_directory))
            async with asyncio.timeout(5):
                while restored_shell_view.working_directory != str(shell_directory):
                    await pilot.pause(.02)
            assert shell.working_directory == str(shell_directory)
            if evidence_path := os.environ.get("L0A_EVIDENCE"):
                evidence = Path(evidence_path)
                evidence.mkdir(parents=True, exist_ok=True)
                app.save_screenshot("retained-shell.svg", path=str(evidence))
                (evidence / "shell-publication.json").write_text(json.dumps({
                    "terminal_paint": terminal_paint,
                    "directory_changed_through_original_stream": True,
                    "same_shell_task_process_model": True,
                    "same_command_widget_source": True,
                    "same_terminal_widget_model": True,
                    "active_shell_subscriptions": len(shell.events.subscriptions),
                    "provider_calls": 0,
                }, indent=2) + "\n")
            await select(app, pilot, app.workspace_sessions.require(third))
            assert second.query_one(Conversation) is second_surface
            assert second.presentation.sources.shell is shell
            sidebar = app.selected_session.query_one("#thread-sidebar", SideBar)
            assert not sidebar._panels_loaded
            sidebar.reveal()
            async with asyncio.timeout(5):
                await sidebar.wait_content_ready()
            assert sidebar._panels_loaded and sidebar.query_one("#plan-panel")
            other_project = root / "other-project"
            other_project.mkdir()
            await app.session_navigation.new(lambda: MainScreen(other_project))
            async with asyncio.timeout(5):
                while app.selected_session.conversation._directory_watcher is None:
                    await pilot.pause(.02)
            assert app.selected_session.conversation.project_path == other_project
            assert app.selected_session.conversation._directory_watcher._path == other_project
            await select(app, pilot, app.workspace_sessions.require(third))
            assert app.selected_session.conversation.project_path == root
            assert app.selected_session.conversation._directory_watcher._path == root
            assert app._exception is None
        assert shell_custody.child.retired, "Logical session close leaked its shell process"
        assert shell_operation.task.done(), "Logical session close leaked its reader"
        await asyncio.get_running_loop().shutdown_default_executor()
    print("RETAINED_PHYSICAL_ABA_DRAFT_UNDO_SHELL_OWNER_CLOSE_PASS")


if __name__ == "__main__":
    asyncio.run(startup_hydration() if "--startup-only" in sys.argv else
                frame_admission() if "--frame-only" in sys.argv else
                response_projection() if "--response-only" in sys.argv else
                danger_projection() if "--danger-only" in sys.argv else
                layout_preferences() if "--layout-only" in sys.argv else main())
