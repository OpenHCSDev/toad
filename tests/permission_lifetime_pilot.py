"""Installed RPC + mounted permissions across real surface retirement."""
import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.comms import Comms
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.widgets.conversation import Conversation
from toad.widgets.question import Question


async def main():
    with tempfile.TemporaryDirectory(prefix="permission-lifetime-", dir="/var/tmp") as directory:
        root = Path(directory)
        wire = Comms(root / "wire")
        identity = wire.messaging.initialize_private_initial_protocol()
        os.environ.update(AGENT_COMMS_ROOT=str(wire.root), AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=identity,
                          XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"))
        project = root / "project"
        project.mkdir()
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            view = app.screen.conversation
            agent = Agent(project, {"name": "RPC", "run_command": {"*": "true"}}, "session")
            view.agent = agent
            await pilot.pause()
            for lifecycle in ("grant", "reject", "replace", "stop"):
                params = {"sessionId": "session", "options": [
                    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject", "name": "Reject", "kind": "reject_once"}],
                    "toolCall": {"toolCallId": lifecycle, "title": lifecycle, "kind": "read"}}
                task = asyncio.create_task(agent.server.call({"jsonrpc": "2.0", "id": 1,
                    "method": "session/request_permission", "params": params}))
                await pilot.pause()
                request, = agent.permissions.pending
                assert view.prompt._ask is not None
                parent = view.parent
                agent.detach_surface(view)
                await view.remove()
                assert request.pending
                replacement = Conversation(project)
                await parent.mount(replacement)
                replacement.agent = agent
                view = replacement
                await pilot.pause()
                ask = view.prompt._ask
                assert ask is not None and request.pending
                if lifecycle == "replace":
                    agent.session_id = "replacement"
                elif lifecycle == "stop":
                    await agent.stop()
                else:
                    desired = "allow" if lifecycle == "grant" else "reject"
                    index, answer = next((index, answer) for index, answer in enumerate(ask.options) if answer.id == desired)
                    view.prompt.on_question_answer(Question.Answer(index, answer, ask))
                result = await asyncio.wait_for(task, 5)
                await pilot.pause()
                assert not agent.permissions.pending and view.prompt._ask is None
                outcome = result["result"]["outcome"]
                if lifecycle in ("replace", "stop"):
                    assert outcome == {"outcome": "cancelled"}
                else:
                    assert outcome == {"outcome": "selected", "optionId": desired}
                agent.session_id = "session"
                assert app._exception is None
            await agent.stop()
    print("PASS: installed RPC/mounted grant, reject, session replacement and stop after actual surface removal/rebind")


if __name__ == "__main__":
    asyncio.run(main())
