"""An interrupted mounted USER send is not replayable while its worker survives."""

from __future__ import annotations
from toad.core import input_events
from toad.navigation_target import NavigationContext

from toad.navigation_target import DirectTarget, channel_target

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent_comms.comms import wire
from default_route_pilot import private_root, route

from toad import messages
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from runtime_fixture import refresh_comms


async def main() -> None:
    if os.name != "posix":
        raise RuntimeError("private route pilot needs POSIX")
    with tempfile.TemporaryDirectory(
        prefix="toad-cancel-", dir="/dev/shm"
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        root, root_id = private_root(sandbox / "wire", sandbox, "INITIAL")
        with patch.dict(
            os.environ,
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(sandbox / "config"),
                "XDG_DATA_HOME": str(sandbox / "data"),
                "XDG_STATE_HOME": str(sandbox / "state"),
            },
        ):
            os.environ.pop("AGENT_COMMS_ROOT", None)
            route(home, root, root_id)
            app = ToadApp(project_dir=str(sandbox))
            async with app.run_test(size=(105, 32)) as pilot:
                await pilot.pause()
                owner_mode = app.selected_mode
                await DirectTarget("peer").open(NavigationContext(app, owner_mode, sandbox, "user"))
                view = app.screen.query_one(CommsChatView)
                original_send = view._wire.messaging.send_user_message
                started = threading.Event()
                release = threading.Event()
                settled = threading.Event()
                calls = 0

                def delayed_send(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    started.set()
                    try:
                        if not release.wait(8):
                            raise TimeoutError("send worker was not released")
                        return original_send(*args, **kwargs)
                    finally:
                        settled.set()

                with patch.object(view._wire.messaging, 'send_user_message', delayed_send):
                    event = input_events.UserInputSubmitted("CANCELLED-IN-FLIGHT")
                    task = asyncio.create_task(view.submit_input(event))
                    assert await asyncio.to_thread(started.wait, 8)
                    task.cancel()
                    await task
                    assert view._human_admission_blocked
                    assert view.prompt.text == event.body
                    assert view.prompt.prompt_text_area.disabled
                    await view.submit_input(event)
                    assert calls == 1
                    release.set()
                    assert await asyncio.to_thread(settled.wait, 8)
                    await pilot.pause()
                    await view.submit_input(event)
                    assert calls == 1
                    assert [row.body for row in wire(root).bus.log.full_history()].count(
                        event.body
                    ) == 1

                # A durable receipt may arrive before mounting finishes. UI
                # cancellation at that edge must preserve its identity and
                # disable compose, rather than offering a second send.
                await channel_target("#team").open(NavigationContext(app, owner_mode, sandbox, "user"))
                channel = app.screen.query_one(CommsChatView)
                await refresh_comms(channel)
                entered_paint, release_paint = asyncio.Event(), asyncio.Event()
                original_mount = channel.message_history.mount_page

                async def delayed_paint(page, *, older):
                    if any(
                        message.body == "POSTRECEIPT-CANCEL"
                        for message in page.messages
                    ):
                        entered_paint.set()
                        await release_paint.wait()
                    return await original_mount(page, older=older)

                with (
                    patch.object(channel.message_history, "mount_page", delayed_paint),
                    patch.object(
                        channel._wire.messaging,
                        'send_user_message',
                        wraps=channel._wire.messaging.send_user_message,
                    ) as sender,
                ):
                    postreceipt = input_events.UserInputSubmitted("POSTRECEIPT-CANCEL")
                    pending = asyncio.create_task(channel.submit_input(postreceipt))
                    async with asyncio.timeout(8):
                        await entered_paint.wait()
                    rows = [
                        row
                        for row in wire(root).bus.log.full_history()
                        if row.body == postreceipt.body
                    ]
                    assert len(rows) == 1 and sender.call_count == 1
                    pending.cancel()
                    await pending
                    assert channel._human_admission_blocked
                    assert channel.prompt.text == postreceipt.body
                    assert channel.prompt.prompt_text_area.disabled
                    assert str(rows[0].seq) in channel.status
                    assert rows[0].message_id in channel.status
                    await channel.submit_input(postreceipt)
                    assert sender.call_count == 1
                    release_paint.set()
            # Cancelling UI workers does not cancel their active to_thread
            # calls. Drain those writes before deleting the disposable wire.
            await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
