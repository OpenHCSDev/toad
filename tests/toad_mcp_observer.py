"""Toad-side observer adapter for the linked MCP acceptance harness.

Owned by the Toad repository; the harness (agent-comms) drives real Pi/ACP.
`open_observer(case, artifact_dir)` mounts a real headless Toad app, forwards
actual ACP session updates through the production Agent path, exposes the
production permission entry point with an explicit simulated user, and records
what the conversation actually rendered.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any, AsyncIterator, cast

from toad.screens.main import MainScreen
from toad.widgets.note import Note


_SESSION_ID = "mcp-acceptance"
_AGENT_DATA = {
    "name": "Fixture",
    "identity": "fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}


def _notes(view: Any) -> list[str]:
    return [
        str(widget.render())
        for widget in view.contents.children
        if isinstance(widget, Note)
    ]


class Observer:
    """Forwarder onto the production Agent/Conversation path."""

    def __init__(self, app: Any, pilot: Any, agent: Any, view: Any) -> None:
        self._app, self._pilot, self._agent, self._view = app, pilot, agent, view
        self.permission_presented = asyncio.Event()
        self.permission_requests: list[dict[str, Any]] = []

    async def session_update(self, session_id: str, update: dict[str, Any]) -> None:
        """Consume one actual ACP session/update payload including its _meta."""
        # The adapter adopts the harness's real session identity once, exactly
        # like a resumed Toad session would.
        if self._agent.session_id != session_id:
            self._agent.session_id = session_id
        meta = update.get("_meta")
        payload = {key: value for key, value in update.items() if key != "_meta"}
        self._agent.rpc_session_update(session_id, payload, meta)
        await self._pilot.pause(0.02)

    async def request_permission(self, **kwargs: Any) -> Any:
        """Production permission entry point; the simulated user answers below."""
        self.permission_requests.append(kwargs)
        self.permission_presented.set()
        return await self._agent.rpc_request_permission(**kwargs)

    async def answer_permission(self, option_id: str) -> None:
        """Explicit simulated-user selection; never automatic, never forged IDs."""
        prompt = self._view.prompt
        ask = prompt._ask
        assert ask is not None, "No permission prompt is currently presented"
        for index, answer in enumerate(ask.options):
            if answer.id == option_id:
                from toad.widgets.question import Question

                prompt.on_question_answer(Question.Answer(index, answer, ask))
                await self._pilot.pause(0.05)
                return
        raise AssertionError(f"Option {option_id!r} was not offered to the user")

    def rendered_notes(self) -> list[str]:
        return _notes(self._view)

    def mcp_live_notes(self) -> list[str]:
        return [note for note in _notes(self._view) if "MCP live" in note]

    def rejected_updates(self) -> int:
        return sum("Invalid ACP update rejected" in note for note in _notes(self._view))


@asynccontextmanager
async def open_observer(case: str, artifact_dir: Path) -> AsyncIterator[Observer]:
    """Mount a real headless Toad conversation for one acceptance case."""
    from runtime_fixture import ToadApp

    root = Path(artifact_dir).resolve()
    os.environ.update(
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_DATA_HOME=str(root / "data"),
        XDG_STATE_HOME=str(root / "state"),
        AGENT_COMMS_ROOT=str(root / "wire"),
    )
    app = ToadApp(project_dir=str(root / "project"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MainScreen)
        view = screen.conversation
        from toad.acp.agent import Agent
        from toad.agent_schema import Agent as AgentData

        agent = Agent(
            root / "project", cast(AgentData, _AGENT_DATA), _SESSION_ID
        )
        agent._message_target = view
        yield Observer(app, pilot, agent, view)
        assert app._exception is None, "Toad observer hit an unexpected exception"
    await asyncio.get_running_loop().shutdown_default_executor()
