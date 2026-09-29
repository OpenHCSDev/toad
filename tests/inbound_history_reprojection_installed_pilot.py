"""One continuously open real UI/ACP/native recipient under history pressure."""
import asyncio
import json
import sys

from agent_comms.threads import Thread
from l0a_native_installed_pilot import main, until
from receiver_inbound_installed_pilot import paint
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.session_tabs import SessionLabel
from toad.screens.comms import CommsScreen
from runtime_fixture import wait_channel_roster
from toad.widgets.observed_thread_activity import ObservedThreadActivity


async def send_channel(comms, text):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent_comms.cli", "send", "--from", "sender",
        "--to", "#team", "--body", text,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout, stderr)
    return comms.bus.log.message_by_id(json.loads(stdout)["id"])


def matching(view, sequence):
    return [block for block in view.contents.query(IncomingMessage)
            if block.sequence == sequence]


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    app.settings.ui.prune_low_mark = 100
    app.settings.ui.prune_excess = 0
    comms.registry.declare(Thread("sender", frozenset({"team"}), str(app.project_dir)))
    message = await send_channel(comms, "@beta OLD_CHANNEL_MESSAGE_PROOF")
    await until(pilot, entered.is_set)
    await until(pilot, lambda: bool(matching(view, message.seq)))
    original = matching(view, message.seq)[0]
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    assert len(requests) == 1
    print("REAL_AGENT_CHANNEL_MESSAGE_AND_NATIVE_RECEIPT", flush=True)

    # Trigger real activity publications, then a substantial native response.
    # Keep the same selected conversation throughout, as in the user's report.
    observed = view.query_one(ObservedThreadActivity)
    entered.clear()
    release.clear()
    hold_next.set()
    view.prompt.text = "UNRELATED_NEW_NATIVE_TURN"
    view.prompt.prompt_text_area.focus()
    await pilot.press("enter")
    await until(pilot, entered.is_set)
    observed.refresh_observation()
    await pilot.pause(.3)
    assert matching(view, message.seq) == [original]
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    await until(pilot, lambda: "LONG_NATIVE_HISTORY" in paint(app), seconds=30)
    observed.refresh_observation()
    await pilot.pause(.5)
    assert app.selected_session.conversation is view
    assert matching(view, message.seq) == [original], "Old inbound was discarded and appended again"
    assert len(requests) == 2
    print("SAME_OPEN_VIEW_NATIVE_ACTIVITY_AND_HISTORY_PRESSURE_NO_REPLAY", flush=True)

    # ACP reconnect is additional coverage; it must not repeat a native input.
    before = len(requests)
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    assert agent.session.connected
    observed.refresh_observation()
    await pilot.pause(.3)
    assert matching(view, message.seq) == [original]
    assert len(requests) == before
    print("REAL_ACP_RECONNECT_NO_PROVIDER_REPLAY", flush=True)

    view.window.focus(scroll_visible=False)
    await pilot.press("pageup", "pageup", "pageup", "pageup")
    await pilot.pause(.5)
    print("ACTUAL_HISTORY_GEOMETRY", view.contents.virtual_size.height, view.window.scroll_y, flush=True)
    assert view.contents.virtual_size.height > app.settings.ui.prune_low_mark
    fresh = await send_channel(comms, "@beta FRESH_CHANNEL_MESSAGE_PROOF")
    await until(pilot, lambda: bool(matching(view, fresh.seq)))
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    observed.refresh_observation()
    await pilot.pause(.3)
    print("OLD_WIRE_PRESENTATIONS_AFTER_PRESSURE", len(matching(view, message.seq)),
          [block is original for block in matching(view, message.seq)], flush=True)
    assert matching(view, message.seq) == [original]
    assert len(matching(view, fresh.seq)) == 1
    assert len(requests) == 3
    expected = next(receipt.state for receipt in comms.views.recent_notifications("beta")
                    if receipt.message is not None and receipt.message.seq == message.seq)
    assert str(original.query_one(".assignment-handling").render()) == f"Handling: {expected}"
    assert app._exception is None
    print("FRESH_INPUT_ONE_WIRE_IDENTITY_AND_LATE_HANDLING_IN_PLACE", flush=True)

    first = app.selected_session
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(item for item in sidebar.query(CommsRow) if item.target_name == "#team")
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row)
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
    label = next(item for item in app.screen.query(SessionLabel) if item.id == first.id)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(label, offset=(label.size.width // 2, 0))
    await until(pilot, lambda: app.selected_session is first)
    returned = first.conversation
    observed = returned.query_one(ObservedThreadActivity)
    observed.refresh_observation()
    await until(pilot, lambda: bool(matching(returned, message.seq)) and bool(matching(returned, fresh.seq)))
    assert len(matching(returned, message.seq)) == len(matching(returned, fresh.seq)) == 1
    assert matching(returned, message.seq)[0].clock.timestamp == message.timestamp
    assert len(requests) == 3
    assert app._exception is None
    print("PHYSICAL_CHANNEL_BAR_AND_RECIPIENT_TAB_RETURN_ONE_RECORDED_WIRE_MESSAGE_NO_REPLAY", flush=True)


def reply(request, number):
    content = ("\n\n".join("\n".join(f"LONG_NATIVE_HISTORY {block}:{line}" for line in range(8))
                           for block in range(35)) if number == 2 else f"NATIVE_RESPONSE_{number}")
    return {"role": "assistant", "content": content}, "stop"


if __name__ == "__main__":
    asyncio.run(main(acceptance=acceptance, provider_reply=reply, provider_request_budget=3))
