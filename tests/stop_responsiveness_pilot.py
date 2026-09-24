"""Stop waits off the UI loop, survives view closure, and reports failures."""

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-stop-responsive-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        for name in ("actor", "victim", "refuses-stop"):
            comms.register(Thread(name, frozenset(), str(root)))
        started, release = threading.Event(), threading.Event()
        stopped = []
        notices = []
        original_stop = type(comms)._stop_unlocked

        def slow_stop(self, name):
            stopped.append(name)
            if name == "refuses-stop":
                raise RuntimeError("Refused test stop")
            started.set()
            # Comms.stop holds its actual shared wire lock here. Other UI
            # readers must remain asynchronous while the process is stopping.
            if not release.wait(8):
                raise TimeoutError("Test shutdown gate was not released")
            return original_stop(self, name)

        app = ToadApp(project_dir=str(root))
        try:
            async with app.run_test(size=(125, 40)) as pilot:
                await pilot.pause()
                source = app.current_mode
                other = (await app.new_session_screen(app.get_main_screen)).mode_name
                dm = await app.open_comms_session(owner_mode=other, project_path=root,
                    me="actor", target="victim", kind="dm")
                channel = await app.open_comms_session(owner_mode=other, project_path=root,
                    me="actor", target="#all", kind="channel")
                await pilot.pause()
                await app.switch_mode(source)
                sidebar = app.screen.query_one(CommsSidebar)
                await sidebar.sync_sessions()
                row = next(row for row in sidebar.query(CommsRow) if row.target_name == "victim")
                real_notify = app.notify

                def notify(message, **kwargs):
                    notices.append((message, kwargs.get("severity")))
                    return real_notify(message, **kwargs)

                with patch.object(type(comms), "_stop_unlocked", slow_stop), patch.object(app, "notify", notify):
                    await pilot.click(row, button=3)
                    await pilot.pause()
                    stop = next(item for item in app.screen.query(ContextMenuItem) if item.action == "comms_stop")
                    await pilot.click(stop)
                    await until(started.is_set)
                    await pilot.pause()
                    assert app.pending_thread_actions["victim"] == "Stopping…"
                    assert "Stopping…" in row.render().plain
                    # UI callbacks and keystrokes must complete before shutdown.
                    app.screen.conversation.prompt.focus()
                    await pilot.press(*"keep typing")
                    assert app.screen.conversation.prompt.text == "keep typing"
                    await asyncio.wait_for(app.switch_mode(dm), 2)
                    await pilot.pause()
                    await asyncio.wait_for(app.switch_mode(channel), 2)
                    await pilot.pause()
                    app.screen.query_one(CommsSidebar).post_message(
                        CommsSidebar.ThreadAction("victim", "comms_stop")
                    )
                    await pilot.pause()
                    assert stopped == ["victim"]
                    assert not release.is_set()
                    await asyncio.wait_for(app.close_session_mode(source), 2)
                    assert "victim" in app.pending_thread_actions
                    release.set()
                    await until(lambda: not app.pending_thread_actions)
                    assert comms.registry.status("victim").value == "stopped"
                    assert any("Stopped @victim" in message for message, _ in notices)
                    app.invoke_thread_action("comms_stop", "refuses-stop", "actor")
                    await until(lambda: not app.pending_thread_actions)
                    assert comms.registry.status("refuses-stop").active
                    assert any(message == "Refused test stop" and severity == "error"
                               for message, severity in notices)
                    assert app._exception is None
        finally:
            release.set()
            await asyncio.get_running_loop().shutdown_default_executor()
    print("stop: responsive typing/navigation under shutdown lock; no duplicates; survives close; errors visible")


if __name__ == "__main__":
    asyncio.run(main())
