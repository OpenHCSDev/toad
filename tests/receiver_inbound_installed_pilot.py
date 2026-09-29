"""One-owner native channel send through ACP and the recipient's visible Toad tab."""

import asyncio
import json
import sys

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main, until
from toad.widgets.incoming_message import AssignedIncomingMessage, IncomingMessage
from toad.widgets.session_details import SessionDetails


def paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def acceptance(app, pilot, agent, comms: Comms, entered, release, hold_next, requests):
    owner_mode = app.selected_mode
    project = app.project_dir
    comms.registry.declare(Thread("sender", frozenset({"team"}), str(project)))
    entered.clear()
    release.clear()
    hold_next.set()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent_comms.cli", "send", "--from", "sender",
        "--to", "#team", "--body", "@beta RECEIVER_NATIVE_INBOUND_PROOF",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout, stderr)
    receipt = json.loads(stdout)
    message = comms.bus.log.message_by_id(receipt["id"])
    assert message is not None and message.sender == "sender" and message.target == "#team"
    await until(pilot, entered.is_set)
    assert app.selected_mode == owner_mode
    details = app.selected_session.query_one(SessionDetails)
    await until(pilot, lambda: "Latest inbound #team from @sender" in str(details.title))
    await until(pilot, lambda: "Latest inbound #team from @sender" in paint(app))
    assert "RECEIVER_NATIVE_INBOUND_PROOF" in str(details.activity.render())
    await until(pilot, lambda: any(
        block.sequence == message.seq
        for block in app.selected_session.query(AssignedIncomingMessage)
    ))
    block = next(block for block in app.selected_session.query(AssignedIncomingMessage)
                 if block.sequence == message.seq)
    assert "RECEIVER_NATIVE_INBOUND_PROOF" in block.text
    assert "Handling:" in str(block.query_one(".assignment-handling").render())
    await until(pilot, lambda: "RECEIVER_NATIVE_INBOUND_PROOF" in paint(app))
    assert "Handling:" in paint(app)
    print("AGENT_TO_CHANNEL_TO_RECEIVER_NATIVE_TAB_ACTUAL_PAINT", flush=True)
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    expected = next(notice.state for notice in comms.views.recent_notifications("beta")
                    if notice.message is not None and notice.message.seq == message.seq)
    await until(pilot, lambda: f"Handling: {expected}" ==
                str(block.query_one(".assignment-handling").render()))
    assert sum(item.sequence == message.seq for item in
               app.selected_session.query(AssignedIncomingMessage)) == 1
    assert sum(item.sequence == message.seq for item in
               app.selected_session.query(IncomingMessage)) == 1
    assert len(requests) == 1, requests
    assert app._exception is None, app._exception


if __name__ == "__main__":
    asyncio.run(main(acceptance=acceptance, provider_request_budget=2))
