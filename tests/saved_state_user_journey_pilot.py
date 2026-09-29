"""Continuous saved-state journey on installed App/ACP/Pi, using actual clicks."""

import asyncio
import os
from pathlib import Path

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.acp_extension import RequestFailedUpdate, decode_updates
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture
from l0a_native_installed_pilot import until
from native_session_retention_pilot import InstalledApp, conversation_paint
from runtime_fixture import wait_channel_roster

from toad.screens.comms import CommsScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.session_tabs import SessionLabel


class SavedStateSubscriber:
    """Observe real ACP failures while producing representative native history."""

    def __init__(self):
        self.failures = []

    def require_success(self):
        assert not self.failures, "\n".join(failure.feedback for failure in self.failures)

    async def session_update(self, **kwargs):
        for fact in decode_updates(kwargs["update"].get("_meta")):
            if isinstance(fact, RequestFailedUpdate):
                self.failures.append(fact.failure)


async def prepare_saved_state(comms, project, requests, entered, release, hold_next):
    release.set()
    client = CommsClient(
        comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
    )
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        for number in range(2):
            prompt = f"SAVED_READER_{number}\n\n" + "\n\n".join(
                f"Retained reader paragraph {row}: actual native history." for row in range(12)
            )
            async with asyncio.timeout(20):
                await client.prompt("beta", [TextContentBlock(type="text", text=prompt)])
            subscriber.require_success()
        assert len(requests) == 2, "Saved-state preparation must reach the actual provider"
        native = Path(comms.registry.require("beta").session_file)
        assert "SAVED_READER_0" in native.read_text()
    finally:
        await client.shutdown()

    comms.threads.register(Thread(
        "gamma", frozenset({"team"}), str(project),
        model="selected-offline/fixture", thinking_level="off",
    ))
    comms.messaging.send("beta", "#team", "SAVED_CHANNEL_MESSAGE")
    print("PREPARED_REAL_NATIVE_SAVED_HISTORY_AND_CHANNEL", len(requests), flush=True)


def screen_paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def click_tab(app, pilot, session_id):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == session_id)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(tab), f"Tab {session_id} was not physically clickable"
    await until(pilot, lambda: app.selected_session.id == session_id)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    first = app.selected_session
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert "SAVED_READER_1" in conversation_paint(app.screen)
    print("SAVED_HISTORY_STARTUP_ACTUAL_PAINT", flush=True)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    channel_row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    channel_row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(channel_row), "Channel-bar row was not physically clickable"
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
    channel = app.selected_session
    await until(pilot, lambda: bool(channel.query(CommsChatView)))
    await until(pilot, lambda: "SAVED_CHANNEL_MESSAGE" in screen_paint(app))
    assert app._exception is None
    print("CHANNEL_BAR_CLICK_COMMS_SCREEN_SAVED_HISTORY_PAINT", flush=True)
    await click_tab(app, pilot, first.id)
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert len(requests) == 2, "Channel/tab navigation replayed an input"
    print("SAVED_CHANNEL_AGENT_RETURN_NO_REPLAY", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, prepare_state=prepare_saved_state, acceptance=acceptance,
    ))
