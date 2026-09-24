"""A sidebar-opened thread keeps the same correct tab label active and inactive."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.messages import CoordinationUpdate
from toad.agent import AgentReady
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar
from toad.widgets.session_tabs import SessionLabel, SessionsTabs


async def main(title: str | None = None, *, cold_metadata: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="toad-existing-tab-title-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        comms = wire(root / "wire")
        project = root / "other-project"
        project.mkdir()
        comms.register(Thread("owner", frozenset({"acp"}), str(root), pid=os.getpid(), title="Owner"))
        comms.register(Thread("existing-thread", frozenset({"acp"}), str(project), pid=os.getpid(), title=title))
        expected_title = title or "existing-thread"
        started, release = asyncio.Event(), asyncio.Event()
        observations = []

        async def start(agent: Agent, target) -> None:
            agent._message_target = target

            async def attach() -> None:
                started.set()
                await release.wait()
                agent._publish_coordination_metadata({"_meta": {"agentComms": {
                    "thread": "existing-thread", "title": expected_title,
                    "wireRoot": str(root / "wire"), "worktree": str(project),
                }}}, initial=True)
                target.post_message(AgentReady())

            agent._task = asyncio.create_task(attach())

        app = ToadApp(project_dir=str(root))
        original_compose = SessionsTabs.compose

        def compose_before_metadata(tabs: SessionsTabs):
            # Control the cold metadata boundary: labels are constructed before
            # the roster snapshot is available, but it arrives before Mount.
            # This reproduces a cache/DOM disagreement, not a server title change.
            snapshot = app._sidebar_snapshot
            if cold_metadata:
                app._sidebar_snapshot = None
            try:
                yield from original_compose(tabs)
            finally:
                app._sidebar_snapshot = snapshot

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            app.screen._agent = {"name": "Fixture", "identity": "agent-comms.openhcs.dev",
                                 "short_name": "fixture", "run_command": {"*": "false"},
                                 "protocol": "acp"}
            await app.screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"), persistence="persistent", transport="stdio",
            ))
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            row = next(row for row in sidebar.query(CommsRow) if row.target_name == "existing-thread")
            row.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            with patch.object(Agent, "start", start), patch.object(SessionsTabs, "compose", compose_before_metadata):
                assert await pilot.click(row)
                await asyncio.wait_for(started.wait(), 5)
                await pilot.pause()
                opened = app.current_mode
                assert opened != owner

                def observe(phase: str) -> None:
                    expected = next(tab.title for tab in app.open_tabs if tab.mode_name == opened)
                    label = app.screen.query_one(f"SessionLabel#{opened}", SessionLabel).render().plain
                    cache = app.screen.query_one(SessionsTabs)._last_tabs
                    cached = next(tab.title for tab in cache if tab.mode_name == opened)
                    rendered = app.screen.query_one(f"SessionLabel#{opened}", SessionLabel)
                    frame = app.screen._compositor.render_strips()
                    painted = frame[rendered.region.y].text[rendered.region.x:rendered.region.right].strip()
                    observations.append((phase, label, expected, cached, painted))

                observe("new active view, before ACP attachment")
                await app.switch_mode(owner)
                await pilot.pause()
                observe("inactive tab")
                await app.switch_mode(opened)
                await pilot.pause()
                observe("reactivated tab")
                release.set()
                async with asyncio.timeout(5):
                    while not app.screen.conversation.agent_ready:
                        await pilot.pause(.02)
                await pilot.pause()
                observe("attached active tab")
                assert all(label == expected == cached == painted and expected_title in label
                           for _, label, expected, cached, painted in observations), observations
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("existing-thread sidebar click: initial, inactive, reactivated and attached labels match")


if __name__ == "__main__":
    asyncio.run(main(cold_metadata=True))
    asyncio.run(main("Already named thread"))
