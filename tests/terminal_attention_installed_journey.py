"""Real saved Pi/ACP -> normal terminal App -> queued questions and private D-Bus.

The desktop receiver is a private real D-Bus service; notifypy/notify-send and
the Linux driver run unchanged. No owner's desktop, live bus or provider is used.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import partial
import json
import fcntl
import struct
import termios
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.acp import CommsClient
from acp.schema import TextContentBlock
from jeepney import HeaderFields, MessageType, new_method_return
from jeepney.bus_messages import message_bus
from jeepney.io.asyncio import open_dbus_connection
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from saved_state_user_journey_pilot import SavedStateSubscriber, click_tab
from toad.answer import Answer
from toad.screens.main import MainScreen
from toad.setting_choices import AlwaysNotification, NeverNotification
from toad.terminal_attention import BlinkingTerminalTitle, QuietTerminalTitle, IconTitleFrame, TerminalTitle


class DesktopMethod(DeclaredFamily, affix="Method"):
    @classmethod
    def wire_name(cls):
        return cls.__name__.removesuffix("Method")

    @classmethod
    @abstractmethod
    def reply(cls, message, notices): ...


class GetCapabilitiesMethod(DesktopMethod):
    @classmethod
    def reply(cls, message, notices):
        return new_method_return(message, "as", (["body", "icon-static"],))


class GetServerInformationMethod(DesktopMethod):
    @classmethod
    def reply(cls, message, notices):
        return new_method_return(message, "ssss", ("Private acceptance", "Toad", "1", "1.2"))


class NotifyMethod(DesktopMethod):
    @classmethod
    def reply(cls, message, notices):
        notices.append(message.body)
        return new_method_return(message, "u", (len(notices),))


@asynccontextmanager
async def desktop_receiver():
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    address = await asyncio.to_thread(daemon.stdout.readline)
    assert address.startswith("unix:"), address
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = address.strip()
    connection = await open_dbus_connection()
    notices = []
    await connection.send(message_bus.RequestName("org.freedesktop.Notifications", 0))
    while (reply := await connection.receive()).header.message_type != MessageType.method_return:
        pass
    assert reply.body == (1,), reply.body

    async def serve():
        methods = {case.wire_name(): case for case in DesktopMethod.members_with(DesktopMethod)}
        while True:
            message = await connection.receive()
            if message.header.message_type != MessageType.method_call:
                continue
            case = methods[message.header.fields[HeaderFields.member]]
            await connection.send(case.reply(message, notices))

    server = asyncio.create_task(serve())
    try:
        yield notices
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)
        await connection.close()
        daemon.terminate()
        await asyncio.to_thread(daemon.wait, timeout=5)


class PhysicalInstalledApp(InstalledApp):
    @asynccontextmanager
    async def run_test(self, **kwargs):
        async with super().run_test(headless=False, **kwargs) as pilot:
            yield pilot


class BadgeTerminalTitle(QuietTerminalTitle):
    """A declaration-only presentation case; all application callers inherit."""
    def icon(self):
        return "🔖"


def reply(request, number):
    return ({"role": "assistant", "content": "SAVED_ATTENTION_NATIVE_REPLY"}, "stop")


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    client = CommsClient(comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"])
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        async with asyncio.timeout(20):
            await client.prompt("beta", [TextContentBlock(type="text", text="ATTENTION_SAVED_INPUT")])
        subscriber.require_success()
        assert len(requests) == 1
    finally:
        await client.shutdown()


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests, *, notices):
    view = app.selected_session.conversation
    try:
        await until(pilot, lambda: "SAVED_ATTENTION_NATIVE_REPLY" in conversation_paint(app.screen))
    except TimeoutError:
        Path(os.environ["L0A_EVIDENCE"], "startup-frame.txt").write_text("\n".join(
            strip.text for strip in app.screen._compositor.render_strips()))
        Path(os.environ["L0A_EVIDENCE"], "startup-geometry.txt").write_text(repr((
            app.size, app.screen.region, view.window.region, view.window.virtual_size,
            view.window.scroll_y, view.window.max_scroll_y,
            conversation_paint(app.screen))))
        raise
    attention = app.terminal_attention
    settings = app.settings.notifications
    settings.system, settings.enable_sounds = AlwaysNotification, False
    editor = view.prompt.prompt_text_area
    editor.insert("UNSENT_ATTENTION_DRAFT")
    document, undo = editor.document, editor.history
    native_file = Path(comms.registry.require("beta").session_file)
    original_native = native_file.read_bytes()
    answered = []
    asks = [view.ask([Answer("Continue", f"continue-{index}")], f"Question {index}",
                     callback=lambda answer: answered.append(answer.id)) for index in range(3)]
    await until(pilot, lambda: len(notices) == 3 and isinstance(attention.state, BlinkingTerminalTitle))
    assert attention.sources == {view.prompt}
    for index in range(3):
        await until(pilot, lambda: f"Question {index}" in "\n".join(
            strip.text for strip in app.screen._compositor.render_strips()))
        assert view.prompt._ask is asks[index]
        await pilot.press("enter")
        await until(pilot, lambda: len(answered) == index + 1)
        await until(pilot, lambda: view.prompt._ask is not asks[index])
    await until(pilot, lambda: isinstance(attention.state, QuietTerminalTitle))
    assert not attention.sources
    assert editor.document is document and editor.history is undo
    assert editor.text == "UNSENT_ATTENTION_DRAFT"

    # Retirement is exact/idempotent; one cancelled queued Ask does not own
    # a separate scalar increment, and another real source survives it.
    current = view.ask([Answer("Continue", "last")], "Retained attention")
    queued = view.ask([Answer("Continue", "cancelled")], "Cancelled queued attention")
    attention.require(app.selected_session)
    view.prompt.remove_ask(queued)
    view.prompt.remove_ask(current)
    await pilot.pause()
    assert attention.sources == {app.selected_session}
    state = attention.state
    assert isinstance(state, BlinkingTerminalTitle)
    state.advance()
    assert isinstance(state.frame, IconTitleFrame)
    old_frame = state.frame
    settings.blink_title = False
    await until(pilot, lambda: isinstance(attention.state, QuietTerminalTitle))
    await pilot.pause(.55)
    assert state.frame is old_frame, "Disabled title timer kept advancing"
    settings.blink_title = True
    await until(pilot, lambda: isinstance(attention.state, BlinkingTerminalTitle))
    attention.release(app.selected_session)
    attention.release(app.selected_session)
    await until(pilot, lambda: isinstance(attention.state, QuietTerminalTitle))

    # Exercise the changed permission-screen caller on the actual attached
    # Agent's installed ACP request boundary, not a fake Agent/future/view.
    from toad.screens.permissions import PermissionReview
    permission = asyncio.create_task(agent.server.call({"jsonrpc": "2.0", "id": 91,
        "method": "session/request_permission", "params": {
            "sessionId": agent.session_id,
            "options": [{"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                        {"optionId": "reject", "name": "Reject", "kind": "reject_once"}],
            "toolCall": {"toolCallId": "attention-diff", "title": "Permission attention", "kind": "edit",
                         "content": [{"type": "diff", "path": str(view.project_path / "attention.txt"),
                                      "oldText": "old attention", "newText": "new attention"}]}}}))
    try:
        await until(pilot, lambda: isinstance(app.screen, PermissionReview))
        permission_screen = app.screen
        await until(pilot, lambda: "new attention" in "\n".join(
            strip.text for strip in app.screen._compositor.render_strips()))
        assert attention.sources == {permission_screen}
        assert isinstance(attention.state, BlinkingTerminalTitle)
        await pilot.press("a")
        result = await asyncio.wait_for(permission, 10)
        assert result["result"]["outcome"]["optionId"] == "allow", result
        await until(pilot, lambda: isinstance(attention.state, QuietTerminalTitle))
        assert not attention.sources
    finally:
        if not permission.done():
            permission.cancel()
            await asyncio.gather(permission, return_exceptions=True)

    assert BadgeTerminalTitle in TerminalTitle.members_with(TerminalTitle)
    attention.state = BadgeTerminalTitle(attention)
    attention.update()
    await pilot.pause()
    assert isinstance(attention.state, BadgeTerminalTitle)
    attention.state = QuietTerminalTitle(attention)
    attention.update()

    await app.workers.wait_for_complete()
    before = len(notices)
    app.notify("[b]Desktop warning[/b]", title="Boundary", severity="warning", markup=True)
    await until(pilot, lambda: len(notices) == before + 1)
    assert notices[-1][3:5] == ("Boundary", "Desktop warning")
    before = len(notices)
    app.notify("hidden information", title="Suppressed")
    await pilot.pause(.2)
    await app.workers.wait_for_complete()
    assert len(notices) == before
    settings.system = NeverNotification
    attention.notify("disabled policy", title="Suppressed")
    await app.workers.wait_for_complete()
    assert len(notices) == before

    original_mode = app.selected_mode
    other = await app.new_session_screen(lambda: MainScreen(view.project_path), title="Attention second tab")
    await pilot.pause()
    await click_tab(app, pilot, original_mode)
    returned = app.selected_session.conversation
    await until(pilot, lambda: "SAVED_ATTENTION_NATIVE_REPLY" in conversation_paint(app.screen))
    current_editor = returned.prompt.prompt_text_area
    assert current_editor.document is document and current_editor.history is undo
    assert current_editor.text == "UNSENT_ATTENTION_DRAFT"
    await pilot.resize_terminal(112, 34)
    await pilot.pause()
    assert native_file.read_bytes() == original_native and len(requests) == 1
    assert not attention.sources and isinstance(attention.state, QuietTerminalTitle)
    assert app._exception is None
    Path(os.environ["L0A_EVIDENCE"], "journey.json").write_text(json.dumps({
        "pass": True, "native_inputs": len(requests), "answers": answered,
        "desktop_records": [{"title": row[3], "body": row[4]} for row in notices],
        "draft_document_undo_native_preserved": True, "pending_attention": len(attention.sources),
        "installed_attached_agent_diff_permission": "allow", "declaration_only_title_case": True,
    }, indent=2) + "\n")
    print("PASS_INSTALLED_SAVED_NATIVE_QUEUED_ASKS_PRIVATE_DBUS_TITLE_PREFERENCE_TAB_DRAFT",
          file=sys.__stdout__, flush=True)

def physical_terminal():
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 44, 160, 0, 0))
    process = subprocess.Popen([sys.executable, __file__, "--pty-child"],
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    output = bytearray()
    try:
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
            if len(output) > 2_000_000:
                raise AssertionError("Unexpected terminal output growth")
            if process.poll() is not None:
                break
        code = process.wait(timeout=5)
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / "terminal.raw").write_bytes(output)
        assert code == 0, output.decode(errors="replace")[-5000:]
        receipt = json.loads((evidence / "journey.json").read_text())
        assert receipt["pass"]
        titles = [item.split(b"\x07", 1)[0].decode(errors="replace")
                  for item in output.split(b"\x1b]0;")[1:]]
        assert any(title.startswith("👉 ") for title in titles), titles
        assert any(title.startswith("🔖 ") for title in titles), titles
        assert titles[-1].startswith("🐸 "), titles[-3:]
        (evidence / "terminal-titles.json").write_text(json.dumps(titles, indent=2) + "\n")
        print("PASS_PHYSICAL_LINUX_DRIVER_OSC_TITLE_BLINK_AND_IDLE_RESTORATION", flush=True)
        print(json.dumps(receipt, indent=2), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


async def child():
    async with desktop_receiver() as notices:
        await native_fixture(app_type=PhysicalInstalledApp, provider_reply=reply,
                             prepare_state=prepare, acceptance=partial(acceptance, notices=notices))


if __name__ == "__main__":
    if "--pty-child" in sys.argv:
        asyncio.run(child())
    else:
        physical_terminal()
