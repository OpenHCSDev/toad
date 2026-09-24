"""Initial ACP metadata names an existing thread's new tab and saved session."""

import asyncio
from contextlib import nullcontext
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.db import DB
from toad.screens.main import MainScreen
from toad.widgets.session_tabs import SessionLabel


class Response:
    def __init__(self, payload):
        self.payload = payload

    async def wait(self):
        return self.payload


async def check_title(title: str | None) -> None:
    with tempfile.TemporaryDirectory(prefix="toad-initial-title-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        thread = "existing-worker"
        expected = title or thread
        comms = wire(root / "wire")
        comms.register(Thread(thread, frozenset({"acp"}), str(root), title=title))
        payload = {"sessionId": thread, "_meta": {"agentComms": {
            "thread": thread, "title": title, "wireRoot": str(root / "wire"),
            "worktree": str(root), "autoTitle": True,
        }}}
        agent_data = {"name": "fixture", "identity": "agent-comms.openhcs.dev",
                      "run_command": {"*": "false"}}
        app = ToadApp(project_dir=str(root))
        created_titles = []
        create_session = DB.session_new

        async def record_creation(db, name, *args, **kwargs):
            created_titles.append(name)
            return await create_session(db, name, *args, **kwargs)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, MainScreen)
            mode = app.current_mode
            agent = Agent(root, agent_data, None)
            agent.agent_capabilities["loadSession"] = True
            screen.conversation.agent = agent
            agent._message_target = screen.conversation
            with patch.object(agent, "request", return_value=nullcontext()), patch(
                "toad.acp.agent.api.session_new", return_value=Response(payload)
            ), patch.object(DB, "session_new", new=record_creation):
                await agent.acp_new_session()
            await pilot.pause()
            assert created_titles == [expected], ("saved title at creation", created_titles, expected)
            assert app.current_mode == mode, "No tab switch should be needed"
            assert app.session_tracker.get_session(mode).title == expected
            assert expected in screen.query_one(f"SessionLabel#{mode}", SessionLabel).render().plain
            assert agent.session_pk is not None
            assert (await DB().session_get(agent.session_pk))["title"] == expected
            assert comms.registry.require(thread).title == title, "Presenting a title must not rename the thread"

            # A new view of the existing server session, backed by its saved row.
            loaded = await app.new_session_screen(lambda: MainScreen(root))
            screen = app.screen
            resumed = Agent(root, agent_data, thread, agent.session_pk)
            screen.conversation.agent = resumed
            resumed._message_target = screen.conversation
            with patch.object(resumed, "request", return_value=nullcontext()), patch(
                "toad.acp.agent.api.session_load", return_value=Response(payload)
            ):
                await resumed.acp_load_session()
            await pilot.pause()
            assert app.current_mode == loaded.mode_name
            assert app.session_tracker.get_session(loaded.mode_name).title == expected
            assert expected in screen.query_one(f"SessionLabel#{loaded.mode_name}", SessionLabel).render().plain
            assert (await DB().session_get(agent.session_pk))["title"] == expected

            app.session_tracker.update_session(loaded.mode_name, title="My explicit label")
            screen.on_comms_session_named(thread)
            assert app.session_tracker.get_session(loaded.mode_name).title == "My explicit label"
            resumed._publish_coordination_metadata({"_meta": {"agentComms": {
                "thread": thread, "wireRoot": str(root / "wire"),
            }}})
            await pilot.pause()
            assert app.session_tracker.get_session(loaded.mode_name).title == "My explicit label"
            assert app._exception is None

        # Explicit input entered during connection takes precedence over the
        # opening snapshot. Non-coordination agents retain their default name.
        agent = Agent(root, agent_data, None)
        agent.agent_capabilities["loadSession"] = True
        agent._pending_session_name = "My pending title"
        saved = AsyncMock(return_value=7)
        updates = Mock()
        with patch.object(agent, "request", return_value=nullcontext()), patch(
            "toad.acp.agent.api.session_new", return_value=Response(payload)
        ), patch.object(DB, "session_new", new=saved), patch.object(
            DB, "session_update_title", new=AsyncMock()
        ), patch.object(agent, "_rename_coordination_thread"), patch.object(agent, "post_message", new=updates):
            await agent.acp_new_session()
        assert saved.call_args.args[0] == "My pending title"
        from toad.acp.messages import SessionInfoUpdate

        assert [call.args[0].title for call in updates.call_args_list
                if isinstance(call.args[0], SessionInfoUpdate)] == ["My pending title"]
        assert Agent._initial_session_title({"sessionId": "generic"}) is None


async def main() -> None:
    await check_title("An already named thread")
    await check_title(None)
    await asyncio.get_running_loop().shutdown_default_executor()
    print("initial metadata title: saved at creation, visible without tab switching, existing-session load, identity fallback")


if __name__ == "__main__":
    asyncio.run(main())
