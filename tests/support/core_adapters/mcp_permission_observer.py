"""Actual Toad UI observer for the frozen real-Pi acceptance harness.

Only this test adapter selects a simulated user's offered Allow once. Production
Toad never automates the package's PTY challenge or permission answers.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from acp.schema import PermissionOption, ToolCallUpdate
from agent_comms.acp_extension import (
    McpClientAcknowledgementUpdate,
    TurnChangedUpdate,
    decode_updates,
)
from agent_comms.execution.launch_root import LaunchRoot
from agent_comms.projects.checkouts import Checkout
from mcp_turn_boundaries import AGENT_DATA, Relay, exercise_boundaries, notes
from textual.pilot import Pilot

from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.comms_root import LocalCoreConnection
from toad.launch_binding import AgentAttached, NoAgent
from toad.screens.main import MainScreen
from toad.widgets.acp_content import ACPToolCallContent
from toad.widgets.conversation import Conversation
from toad.widgets.question import Question
from toad.widgets.tool_content import ToolContent


class Observer:
    def __init__(self, case: str, app: ToadApp, pilot: Pilot, agent: Agent, session: MainScreen, root: Path,
                 relay: Relay):
        self.case, self.app, self.pilot = case, app, pilot
        self.agent, self.session, self.root, self.relay = agent, session, root, relay
        self.receipts: list[list[str]] = []
        self.permissions = 0
        self.permission_presented = asyncio.Event()
        self.disconnected_seen = False
        self.permission_tasks: set[asyncio.Task] = set()

    @property
    def view(self):
        return self.session.conversation

    async def session_update(self, session_id: str, update: dict[str, Any]) -> None:
        """The harness's session is the owner's; Toad's agent holds the relay peer's own. The
        relay sends each update under Toad's id, as the one ACP agent Toad attached to."""
        with (self.root / "toad-updates.jsonl").open("a") as log:
            log.write(json.dumps({"session": session_id, "update": update,
                                  "toad": type(self.agent.session.disposition).__name__}) + "\n")
        await self.relay.update(update, self.agent.session_id)
        with (self.root / "toad-states.jsonl").open("a") as log:
            log.write(json.dumps({"agent": self.agent.current_turn.managed_id,
                                 "view": self.view.turns.managed_id,
                                 "notes": notes(self.view)}) + "\n")
        for fact in decode_updates(update.get("_meta")):
            if isinstance(fact, McpClientAcknowledgementUpdate):
                rendered = notes(self.view)
                assert len(rendered) == 1 and "fixture[project] ready calls=confirm tools=1" in rendered[0]
                assert self.agent.current_turn.managed_id == self.view.turns.managed_id == fact.turn_id
                self.receipts.append(rendered)
                self.app.save_screenshot(str(self.root / "toad-live.svg"))
            if isinstance(fact, TurnChangedUpdate) and not self.agent.current_turn.busy:
                assert self.agent.current_turn.managed_id is self.view.turns.managed_id is None
                assert not notes(self.view)

    async def request_permission(self, *, session_id, tool_call: ToolCallUpdate,
                                 options: list[PermissionOption], **kwargs):
        """The owner hands its ACP models; they cross the relay as the JSON the pipe carries."""
        self.permissions += 1
        asked: dict[str, Any] = {"toolCall": tool_call.model_dump(mode="json", by_alias=True, exclude_none=True),
                 "options": [option.model_dump(mode="json", by_alias=True, exclude_none=True)
                             for option in options]}
        # The relay asks Toad over its ACP pipe and answers with the outcome JSON the pipe
        # carries back, which is what the harness's callback returns. If Toad refuses, the
        # step raises Toad's own error rather than a guessed denial.
        task = asyncio.create_task(self.relay.step(
            {"permission": asked, "session": self.agent.session_id}))
        self.permission_tasks.add(task)
        try:
            # The request crosses the pipe, so wait for the UI to mount the exact Ask before
            # simulated selection (not merely for the request to be sent).
            # A step that ends first (the relay refused it, or Toad answered without asking)
            # gives its own result or error, not a timeout that hides it.
            async with asyncio.timeout(10):
                while self.view.prompt._ask is None and not self.disconnected_seen and not task.done():
                    await self.pilot.pause(.02)
            ask = self.view.prompt._ask
            if self.disconnected_seen or task.done():
                return await task
            assert ask is not None and self.view.prompt.is_mounted
            preview = await self.painted_preview(self.view)
            assert preview == asked["toolCall"]["content"][0]["content"]["text"]
            self.app.save_screenshot(str(self.root / "toad-permission.svg"))
            self.permission_presented.set()
            if os.environ.get("AC_MCP_RETIRE_SURFACE") == "1" and self.case != "disconnect":
                request, = self.agent.permissions.pending
                previous = self.view
                presentation = self.session.presentation
                await presentation.retire(self.session)
                await presentation.evict(self.session)
                assert request.pending and not self.agent.controller.surface.owns(previous)
                assert not previous.is_mounted and presentation.sources.agent_binding is self.agent
                await presentation.prepare(self.session)
                await self.pilot.pause()
                replacement = presentation.widget
                assert isinstance(replacement, Conversation) and replacement is self.view
                assert replacement is not previous
                assert self.agent.controller.surface.owns(replacement)
                ask = replacement.prompt._ask
                assert ask is not None and request.pending
                assert await self.painted_preview(replacement) == preview
                (self.root / "permission-rebind.txt").write_text("Actual native permission remained pending across rich surface removal and remounted on replacement.\n")
            if self.case != "disconnect":
                index, answer = next((i, a) for i, a in enumerate(ask.options)
                                     if (a.kind or "").startswith(os.environ.get("AC_MCP_PERMISSION_ANSWER", "allow")))
                self.view.prompt.on_question_answer(Question.Answer(index, answer, ask))
                await self.pilot.pause()
            result = await task
            if os.environ.get("AC_MCP_RETIRE_SURFACE") == "1" and self.case != "disconnect":
                assert result["outcome"]["outcome"] == "selected"
                assert result["outcome"]["optionId"] == answer.id
                (self.root / "permission-answer.json").write_text(json.dumps(result))
            return result
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.permission_tasks.discard(task)

    async def painted_preview(self, view: Conversation) -> str:
        """The pending Ask's preview text, once it is on screen. Mounting is not composing or
        painting: the preview's content, the options and the call's own text arrive over the
        refreshes after the Ask mounts."""
        async with asyncio.timeout(10):
            while True:
                ask = view.prompt._ask
                previews = [text for content in view.prompt.query(ACPToolCallContent)
                            for text in content.query(ToolContent)]
                frame = "\n".join(strip.text for strip in self.app.screen._compositor.render_strips())
                if (ask is not None and previews and "ACCEPTANCE_ECHO" in frame
                        and any(option.text in frame for option in ask.options)):
                    preview, = previews
                    return preview.get_clipboard_text()
                await self.pilot.pause(.05)

    async def disconnected(self):
        self.disconnected_seen = True
        await self.agent.stop()
        await self.pilot.pause()
        assert self.agent.current_turn.managed_id is None
        assert not notes(self.view)
        assert self.view.prompt._ask is None
        self.app.save_screenshot(str(self.root / "toad-disconnected.svg"))


@asynccontextmanager
async def open_observer(case: str, artifact_dir: Path) -> AsyncIterator[Observer]:
    root = Path(artifact_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "project").mkdir(exist_ok=True)
    env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
           "XDG_STATE_HOME": str(root / "state"), "AGENT_COMMS_ROOT": str(root / "wire")}
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        app = ToadApp(agent_binding=NoAgent(), project_dir=Checkout(root / "project"),
                      connection=LocalCoreConnection.from_launch(LaunchRoot.from_path(root / "wire")))
        async with app.run_test(size=(120, 40)) as pilot:
            # Toad starts with no tab open; the observed session is opened here.
            # The relay peer is the observed session's agent: Toad starts it and attaches over ACP.
            definition = AgentDefinition.decode(AGENT_DATA)
            await app.session_navigation.start_agent_session(AgentAttached(definition), app.project_dir)
            session = app.selected_session
            assert isinstance(session, MainScreen)
            await session.wait_content_ready()
            view = session.conversation
            async with asyncio.timeout(30):
                while not (isinstance(view.agent_binding, Agent) and view.agent_binding.session.settled.is_set()):
                    await pilot.pause(.05)
            agent = view.agent_binding
            relay = await Relay.started(app.project_dir.path, view, pilot)
            observer = Observer(case, app, pilot, agent, session, root, relay)
            try:
                async with exercise_boundaries(relay, agent, view):
                    yield observer
                assert len(observer.receipts) == 1
                assert observer.permissions == (0 if case == "no_controller" else 1)
                assert observer.disconnected_seen == (case == "disconnect")
                assert not notes(observer.view)
                assert app._exception is None
                (root / "toad-evidence.json").write_text(json.dumps({
                    "case": case, "session": observer.agent.session_id,
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
