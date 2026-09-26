"""Actual Toad UI observer for the frozen real-Pi acceptance harness.

Only this test adapter selects a simulated user's offered Allow once. Production
Toad never automates the package's PTY challenge or permission answers.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from mcp_live_status_pilot import AGENT_DATA, exercise_boundaries, notes
from toad.acp.agent import Agent
from toad.screens.main import MainScreen
from toad.widgets.question import Question

SESSION_ID = "project"


class Observer:
    def __init__(self, case, app, pilot, agent, view, root):
        self.case, self.app, self.pilot = case, app, pilot
        self.agent, self.view, self.root = agent, view, root
        self.receipts: list[list[str]] = []
        self.permissions = 0
        self.disconnected_seen = False
        self.permission_tasks: set[asyncio.Task] = set()

    async def session_update(self, session_id: str, update: dict[str, Any]) -> None:
        self.agent.rpc_session_update(session_id, update)
        await self.pilot.pause()
        state = update.get("_meta", {}).get("agentComms", {})
        assert self.agent.session_id == SESSION_ID
        if "mcpClient" in state:
            rendered = notes(self.view)
            assert len(rendered) == 1 and "fixture[project] ready calls=confirm tools=1" in rendered[0]
            assert self.agent._active_turn_id == self.view._managed_turn_id == state["turnId"]
            self.receipts.append(rendered)
            self.app.save_screenshot(str(self.root / "toad-live.svg"))
        if state.get("turnSettled"):
            assert self.agent._active_turn_id is self.view._managed_turn_id is None
            assert self.view._mcp_live_turn is None and not notes(self.view)

    async def request_permission(self, *, session_id, tool_call, options, **kwargs):
        self.permissions += 1
        task = asyncio.create_task(self.agent.rpc_request_permission(
            sessionId=session_id, toolCall=tool_call, options=options,
        ))
        self.permission_tasks.add(task)
        try:
            await self.pilot.pause()
            # A callback scheduled through the actual UI queue must have mounted
            # the exact Ask before simulated selection (not merely received RPC).
            ask = self.view.prompt._ask
            if self.disconnected_seen:
                return await task
            assert ask is not None and self.view.prompt.is_mounted
            self.app.save_screenshot(str(self.root / "toad-permission.svg"))
            if self.case != "disconnect":
                index, answer = next((i, a) for i, a in enumerate(ask.options)
                                     if a.id == "allow-once")
                self.view.prompt.on_question_answer(Question.Answer(index, answer, ask))
                await self.pilot.pause()
            return await task
        finally:
            self.permission_tasks.discard(task)

    async def disconnected(self):
        self.disconnected_seen = True
        await self.agent.stop()
        await self.pilot.pause()
        assert self.agent._active_turn_id is None
        assert self.view._mcp_live_turn is None and not notes(self.view)
        assert self.view.prompt._ask is None
        self.app.save_screenshot(str(self.root / "toad-disconnected.svg"))


@asynccontextmanager
async def open_observer(case: str, artifact_dir: Path) -> AsyncIterator[Observer]:
    from runtime_fixture import ToadApp

    root = Path(artifact_dir).resolve()
    env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
           "XDG_STATE_HOME": str(root / "state"), "AGENT_COMMS_ROOT": str(root / "wire")}
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        app = ToadApp(project_dir=str(root / "project"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            view = app.screen.conversation
            agent = Agent(root / "project", AGENT_DATA, SESSION_ID)
            agent._message_target = view
            view.agent = agent
            await exercise_boundaries(agent, view, pilot)
            observer = Observer(case, app, pilot, agent, view, root)
            try:
                yield observer
                assert len(observer.receipts) == 1
                assert observer.permissions == (0 if case == "no_controller" else 1)
                assert observer.disconnected_seen == (case == "disconnect")
                assert not notes(view) and view._mcp_live_turn is None
                assert app._exception is None
                (root / "toad-evidence.json").write_text(json.dumps({
                    "case": case, "session": agent.session_id,
                    "renderedReceipts": observer.receipts,
                    "permissionDialogs": observer.permissions,
                    "negativeBoundariesPassed": True, "liveProjectionCleared": True,
                    "disconnectCleared": observer.disconnected_seen,
                }, indent=2))
            finally:
                await agent.stop()
                if observer.permission_tasks:
                    await asyncio.gather(*observer.permission_tasks, return_exceptions=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
