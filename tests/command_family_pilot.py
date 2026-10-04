"""Installed command ownership through real saved native/ACP state and X input.

Run with COMMAND297_PHYSICAL=1 under an owned isolated st/Xvfb display. The
existing native fixture owns protocol, native history, loopback provider and
owner retirement; this acceptance owns only observations and physical actions.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time

from acp.schema import AvailableCommandsUpdate
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from runtime_fixture import wait_channel_roster
from saved_state_user_journey_pilot import prepare_saved_state
from toad.screens.comms import CommsScreen
from toad.slash_command import NoArgumentsCommand
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.slash_complete import SlashComplete


class InsertionCommand(NoArgumentsCommand):
    """A new declaration needs no catalog, dispatcher or menu edit."""
    help = "Run the declaration insertion control"

    async def apply(self, conversation):
        conversation.prompt.text = "declaration ran"
        return True


async def external(*arguments):
    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    async with asyncio.timeout(5):
        stdout, stderr = await process.communicate()
    assert process.returncode == 0, (arguments, stderr.decode())
    return stdout.decode()


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    assert os.environ.get("COMMAND297_PHYSICAL") == "1"
    assert os.environ["DISPLAY"] != ":0"
    assert type(app._driver).__name__ == "LinuxDriver"
    evidence = Path(os.environ["L0A_EVIDENCE"])
    started = time.monotonic()
    events = []
    window = (await external("xdotool", "search", "--sync", "--pid", str(os.getppid()))).splitlines()[0]
    geometry = dict(line.split("=", 1) for line in
                    (await external("xdotool", "getwindowgeometry", "--shell", window)).splitlines())
    await external("xdotool", "windowfocus", "--sync", window)

    async def mark(name):
        await pilot.pause(.12)
        (evidence / f"{name}.txt").write_text("\n".join(strip.text for strip in app.screen._compositor.render_strips()))
        (evidence / f"{name}.svg").write_text(app.export_screenshot())
        await external("import", "-display", os.environ["DISPLAY"], "-window", "root", str(evidence / f"{name}.png"))
        events.append({"phase": name, "seconds": time.monotonic() - started,
                       "mode": app.selected_mode, "requests": len(requests)})
        (evidence / "events.json").write_text(json.dumps(events, indent=2))

    async def click(widget, button=1):
        await pilot.pause(.08)
        region = widget.region
        assert widget in app.screen._compositor.visible_widgets and region.width and region.height
        # st has a two-pixel border. Derive cell geometry from the actual window
        # and installed driver's actual terminal dimensions, not fixed XY values.
        x = int(geometry["X"]) + 2 + (region.x + min(2, region.width // 2) + .5) * (int(geometry["WIDTH"]) - 4) / app.size.width
        y = int(geometry["Y"]) + 2 + (region.y + .5) * (int(geometry["HEIGHT"]) - 4) / app.size.height
        await external("xdotool", "mousemove", "--sync", str(round(x)), str(round(y)), "click", str(button))
        await pilot.pause(.1)

    async def submit(view, text):
        await click(view.prompt.prompt_text_area)
        assert app.focused is view.prompt.prompt_text_area
        app.copy_to_clipboard(text)
        await external("xdotool", "key", "--clearmodifiers", "ctrl+v")
        await until(pilot, lambda: view.prompt.text == text)
        if isinstance(app.focused.parent, SlashComplete):
            await external("xdotool", "key", "Escape")
        await external("xdotool", "key", "--clearmodifiers", "Return")
        await pilot.pause(.15)

    first = app.selected_session
    view = first.conversation
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert "SAVED_READER_1" in Path(comms.registry.require("beta").session_file).read_text()
    assert len(requests) == 2
    await mark("01-saved-native")
    before_history = comms.views.full_history()

    async def advertise(names):
        update = AvailableCommandsUpdate.model_validate({
            "sessionUpdate": "available_commands_update",
            "availableCommands": [{"name": name, "description": "ACP source control"} for name in names]})
        # Existing SDK/JSON-RPC boundary on the selected actual ACP agent. This
        # controlled notification does not pretend Pi advertised these names.
        await agent.server.call({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": agent.session_id,
            "update": update.model_dump(by_alias=True, exclude_none=True)}})
        await until(pilot, lambda: [record.name for record in agent.controller.commands] == names)

    await advertise(["pin", "model", "external"])
    await until(pilot, lambda: any(command.command == "/external" for command in view.prompt.slash_commands))
    assert not any(command.command == "/pin" for command in view.prompt.slash_commands)
    assert next(command for command in view.prompt.slash_commands if command.command == "/model").help != "ACP source control"
    await submit(view, "/pin")
    assert len(requests) == 2 and comms.views.full_history() == before_history
    await submit(view, "/copy")
    assert app.clipboard == "beta"
    await submit(view, "/insertion")
    await until(pilot, lambda: view.prompt.text == "declaration ran")
    view.prompt.text = ""  # Discard the declaration's test output, never a submitted input.
    await mark("02-local-collision-newcase")

    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    await click(row)
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
    channel = app.selected_session
    await until(pilot, lambda: bool(channel.query(CommsChatView)))
    chat = channel.query_one(CommsChatView)
    await until(pilot, lambda: chat.agent_ready and "SAVED_CHANNEL_MESSAGE" in "\n".join(strip.text for strip in app.screen._compositor.render_strips()))
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    await click(row, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    menu = {item.action: item.render().plain for item in app.screen.query(ContextMenuItem)}
    context = await chat.command_target_context()
    assert menu == {command.command.removeprefix("/"): command.label(context) for command in await context.command_choices()}
    await mark("03-pointer-menu")
    await click(next(item for item in app.screen.query(ContextMenuItem) if item.action == "pin"))
    await until(pilot, lambda: comms.channels.catalog.read().resolve("#team").pinned)
    await submit(chat, "/pin")
    await until(pilot, lambda: not comms.channels.catalog.read().resolve("#team").pinned)
    await submit(chat, "/copy")
    assert app.clipboard == "#team"
    assert comms.views.full_history() == before_history and len(requests) == 2
    await mark("04-channel-original-target")

    await click(next(label for label in app.screen.query(SessionLabel) if label.id == first.id))
    await until(pilot, lambda: app.selected_session is first and "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert app.selected_session.conversation.agent is agent
    await advertise(["external", "new_external"])
    await until(pilot, lambda: any(command.command == "/new_external" for command in view.prompt.slash_commands))
    assert {record.name for record in agent.controller.commands} == {"external", "new_external"}
    assert not hasattr(view, "agent_slash_commands")
    await mark("05-native-return-hot-publication")
    release.set()
    await submit(view, "/external ORIGINAL_ARGUMENT_297")
    await until(pilot, lambda: len(requests) == 3 and "NATIVE_RESPONSE_3" in conversation_paint(app.screen))
    (evidence / "provider-requests.json").write_text(json.dumps(requests, indent=2))
    # Native owns the coordination envelope. Check the original command as one
    # exact payload line, not equality with the entire composed provider input.
    assert sum(block["text"].splitlines().count("/external ORIGINAL_ARGUMENT_297")
               for block in requests[-1]["messages"][-1]["content"]) == 1
    await until(pilot, lambda: comms.registry.require("beta").active_turn is None)
    native = Path(comms.registry.require("beta").session_file)
    assert "ORIGINAL_ARGUMENT_297" in native.read_text()
    assert len(requests) == 3
    await mark("06-original-forwarded-native-response")
    (evidence / "command-acceptance.json").write_text(json.dumps({
        "status": "PASS", "driver": type(app._driver).__name__, "display": os.environ["DISPLAY"],
        "elapsed_seconds": time.monotonic() - started, "events": events,
        "provider_requests": len(requests), "provider": "isolated localhost only",
        "controlled_advertisement": "real ACP SDK JSON-RPC source publication; not Pi getCommands output",
        "native_session": str(native), "physical_keyboard_and_pointer": True,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance,
        prepare_state=prepare_saved_state, headless=False,
        provider_request_budget=3, fixture_stage=os.environ["COMMAND297_FIXTURE_STAGE"]))
