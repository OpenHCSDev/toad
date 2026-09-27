"""An interrupted mounted USER send is not replayable while its worker survives."""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent_comms.operations import wire
from default_route_pilot import private_root, route

from toad import messages
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView


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
                await app.open_comms_session(
                    owner_mode=app.current_mode,
                    project_path=sandbox,
                    me="user",
                    target="peer",
                    kind="dm",
                )
                view = app.screen.query_one(CommsChatView)
                original_send = view._wire.send_user_message
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

                with patch.object(view._wire, "send_user_message", delayed_send):
                    event = messages.UserInputSubmitted("CANCELLED-IN-FLIGHT")
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
                    assert [row.body for row in wire(root).bus.full_history()].count(
                        event.body
                    ) == 1


if __name__ == "__main__":
    asyncio.run(main())
