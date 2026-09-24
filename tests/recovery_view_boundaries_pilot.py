"""A missing pinned gateway client and dual wire roots fail closed in Toad."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.acp.messages import CoordinationUpdate
from toad.widgets.recovery_view import RecoveryView, _read_gateway
from toad.widgets.side_bar import SideBar, SideBarCollapsible


def dto(owner: str, status: str) -> dict[str, object]:
    return {"schema": 1, "availability": "available", "owner": owner, "sampledAtMs": 1,
            "current": {"status": status, "origin": "wire", "isCurrent": False,
                        "attempt": None, "canRetry": False, "publication": "published"},
            "lastRecovery": None, "connectivity": None}


async def read_only_startup_without_pinned_client():
    # Reproduce the import boundary of an older pinned agent-comms wheel in
    # a new interpreter without replacing this worktree's editable backend.
    code = (
        "import builtins, asyncio\n"
        "original = builtins.__import__\n"
        "def blocked(name, *args, **kwargs):\n"
        "    if name == 'agent_comms.recovery_gateway_client':\n"
        "        raise ModuleNotFoundError(name)\n"
        "    return original(name, *args, **kwargs)\n"
        "builtins.__import__ = blocked\n"
        "import toad.app, toad.screens.main, toad.screens.comms\n"
        "from pathlib import Path\n"
        "from toad.widgets.recovery_view import _read_gateway\n"
        "result = asyncio.run(_read_gateway(Path('/missing/gateway.sock'), 'fixture'))\n"
        "assert result == {'availability': 'unavailable'}\n"
        "print('pinned client absent: startup and enabled read unavailable')\n"
    )
    completed = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", code],
                                         capture_output=True, text=True, check=True, timeout=12)
    assert "pinned client absent" in completed.stdout
    with patch.dict(sys.modules, {"agent_comms.recovery_gateway_client": None}):
        assert await _read_gateway(Path("/missing/gateway.sock"), "fixture") == {
            "availability": "unavailable"
        }


async def dual_root_projection():
    with tempfile.TemporaryDirectory(prefix="toad-recovery-dual-root-") as directory:
        root = Path(directory)
        a, b = root / "A", root / "B"
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(a))
        for target in (a, b):
            wire(target).register(Thread("fixture", frozenset({"test"}), str(root), pid=os.getpid()))
        app = ToadApp(project_dir=str(root))
        requests = []
        blocked = [False]
        began = asyncio.Event()
        release = asyncio.Event()

        async def read(path: Path, thread: str):
            requests.append((path, thread))
            if path.parent.parent == b and blocked[0]:
                began.set()
                await release.wait()
            return dto(thread, "completed" if path.parent.parent == a else "failed")

        with patch("toad.widgets.recovery_view._read_gateway", side_effect=read):
            async with app.run_test(size=(100, 35)) as pilot:
                await pilot.pause()
                owner_mode = app.current_mode
                owner_screen = app.screen
                view = owner_screen.query_one(RecoveryView)
                assert view._wire_root is None and not requests
                # Same name exists in A and B. Trusted ACP says B; the env A
                # must never be used as an implicit recovery identity.
                await owner_screen.on_coordination_update(CoordinationUpdate(
                    thread="fixture", wire_root=str(b), persistence="persistent", transport="stdio"))
                assert view._wire_root == b
                app.settings.set("ui.recovery-view", True)
                owner_screen.query_one("#thread-sidebar", SideBar).reveal()
                view.query_ancestor(SideBarCollapsible).collapsed = False
                async with asyncio.timeout(5):
                    while not requests or "failed" not in view.render().plain:
                        await pilot.pause(.02)
                assert all(path.parent.parent == b and thread == "fixture" for path, thread in requests)
                assert "Execution: failed" in view.render().plain
                assert "completed" not in view.render().plain

                # A channel tab is scoped to env wire A; it cannot borrow
                # owner identity from B merely because both contain fixture.
                mode = await app.open_comms_session(owner_mode=owner_mode, project_path=root,
                                                    me="fixture", target="#any", kind="irc")
                await pilot.pause()
                channel = app.screen.query_one(RecoveryView)
                assert channel._wire_root is None
                reads = len(requests)
                app.screen.query_one("#thread-sidebar", SideBar).reveal()
                channel.query_ancestor(SideBarCollapsible).collapsed = False
                await pilot.pause()
                assert channel.render().plain.startswith("Recovery unavailable")
                assert len(requests) == reads

                # Move the authoritative owner to A while one B fetch is in
                # flight; the stale B result is cancelled and must not paint.
                await app.switch_mode(owner_mode)
                blocked[0] = True
                view.action_refresh()
                async with asyncio.timeout(5):
                    await began.wait()
                await owner_screen.on_coordination_update(CoordinationUpdate(
                    thread="fixture", wire_root=str(a), persistence="persistent", transport="stdio"))
                release.set()
                async with asyncio.timeout(5):
                    while "Execution: completed" not in view.render().plain:
                        await pilot.pause(.02)
                assert view._wire_root == a
                assert requests[-1] == (a / ".recovery-viewer" / "gateway.sock", "fixture")
                assert channel._wire_root == a, "Existing channel tab did not follow trusted owner root"
                await app.switch_mode(mode)
                channel.query_ancestor(SideBarCollapsible).collapsed = False
                async with asyncio.timeout(5):
                    while "Execution: completed" not in channel.render().plain:
                        await pilot.pause(.02)
                assert "failed" not in channel.render().plain
                assert app._exception is None
            await asyncio.get_running_loop().shutdown_default_executor()
    print("recovery dual root: A/env cannot impersonate B/ACP; stale B read cancelled, existing tab rebinds")


async def main():
    await read_only_startup_without_pinned_client()
    await dual_root_projection()


if __name__ == "__main__":
    asyncio.run(main())
