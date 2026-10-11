"""Closing a tab: it leaves the tab bar before its view is torn down, and the
closing view is not projected again on the way out. Times are printed."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.prompt import Prompt



async def main():
    with tempfile.TemporaryDirectory(prefix="toad-close-timing-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        results = []
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            base = app.selected_mode
            for index in range(4):
                mode = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
                conversation = app.selected_session.conversation
                # A bound agent, as an open native tab has: releasing it is
                # what the close must not turn into another projection.
                agent = Agent(root, AgentDefinition("fixture", "Fixture", {"*": "false"}), None)
                conversation.agent = agent
                conversation.bind_agent(agent)
                await conversation.contents.mount(*[
                    AgentResponse(f"Response {i}\n\n" + "long paragraphs.\n\n" * 10)
                    for i in range(14)
                ])
                await pilot.pause()
                prompt = conversation.prompt
                observed, projected = [], []
                teardown = app.workspace_sessions.close
                update_title, sync_configuration = Conversation.update_title, Prompt.sync_configuration
                start = time.perf_counter()

                async def measured_teardown(identity):
                    observed.append(("before_teardown", (time.perf_counter() - start) * 1000))
                    assert not any(tab.mode_name == mode for tab in app.open_tabs), (
                        "Closed tab remained visible during its view's teardown", mode,
                    )
                    result = await teardown(identity)
                    observed.append(("after_teardown", (time.perf_counter() - start) * 1000))
                    return result

                def titled(view, *args, **kwargs):
                    if view is conversation:
                        projected.append("title")
                    return update_title(view, *args, **kwargs)

                def configured(view, *args, **kwargs):
                    if view is prompt:
                        projected.append("prompt configuration")
                    return sync_configuration(view, *args, **kwargs)

                with (patch.object(app.workspace_sessions, "close", measured_teardown),
                      patch.object(Conversation, "update_title", titled),
                      patch.object(Prompt, "sync_configuration", configured)):
                    await app.session_navigation.close(mode)
                observed.append(("closed", (time.perf_counter() - start) * 1000))
                assert [name for name, _ in observed] == ["before_teardown", "after_teardown", "closed"], observed
                assert app.selected_mode == base and mode not in app.tab_order.names
                assert not projected, ("The closing view was projected again", projected)
                assert conversation.agent is None and not conversation.is_attached
                results.append({"round": index, "stages_ms": [(name, round(ms, 2)) for name, ms in observed]})
            print(json.dumps({"boundary": "headless close handler; not terminal pixels", "samples": results}, indent=2))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
