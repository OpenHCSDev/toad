"""Installed Pi/ACP fork: click right Parent and channel child using real UI."""

import asyncio

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from saved_state_user_journey_pilot import prepare_saved_state, fork_and_first_input


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    first = app.selected_session
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    await fork_and_first_input(app, pilot, comms, first, entered, release, hold_next, requests)
    assert app.selected_session is first
    assert len(requests) == 3 and app._exception is None
    print("INSTALLED_PARENT_CHILD_RIGHT_SIDEBAR_CHANNEL_BAR_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, prepare_state=prepare_saved_state, acceptance=acceptance,
    ))
