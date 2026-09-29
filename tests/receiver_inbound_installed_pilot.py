"""One-owner native channel send through ACP and the recipient's visible Toad tab."""

import asyncio

from agent_comms.comms import Comms
from l0a_native_installed_pilot import main, until
from toad import messages
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.session_details import SessionDetails


def paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def acceptance(app, pilot, agent, comms: Comms, entered, release, hold_next, requests):
    owner_mode = app.selected_mode
    project = app.project_dir
    user = comms.messaging.user_identity(str(project)).name
    await channel_target("#team").open(NavigationContext(app, owner_mode, project, user))
    channel = app.selected_session.query_one(CommsChatView)
    entered.clear()
    release.clear()
    hold_next.set()
    await channel.submit_input(messages.UserInputSubmitted("@beta RECEIVER_NATIVE_INBOUND_PROOF"))
    await until(pilot, entered.is_set)
    await app.select_session(owner_mode)
    details = app.selected_session.query_one(SessionDetails)
    await until(pilot, lambda: "Latest inbound #team" in str(details.title))
    await until(pilot, lambda: "Latest inbound #team" in paint(app))
    assert "RECEIVER_NATIVE_INBOUND_PROOF" in str(details.activity.render())
    print("RECEIVER_INBOUND_NATIVE_TAB_ACTUAL_PAINT_WHILE_SELECTED_TURN_RUNNING", flush=True)
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    assert len(requests) == 1, requests
    assert app._exception is None, app._exception


if __name__ == "__main__":
    asyncio.run(main(acceptance=acceptance, provider_request_budget=2))
