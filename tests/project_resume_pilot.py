from toad.widgets.conversation import Conversation
"""A resumed thread's project overrides the directory used to launch Toad."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import psutil
from agent_comms.threads import Thread
from runtime_fixture import private_native_wire
from runtime_fixture import ToadApp
from toad.widgets.project_directory_tree import ProjectDirectoryTree


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-project-resume-") as directory:
        root = Path(directory)
        old, new = root / "launch-project", root / "saved-project"
        old.mkdir()
        new.mkdir()
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
                          AGENT_COMMS_AGENT_BIN="pi", AGENT_COMMS_AGENT_ARGS="",
                          AGENT_COMMS_AGENT_MODELS="test/model")
        comms = private_native_wire(root / "wire")
        comms.threads.register(Thread("saved", frozenset({"acp"}), str(old)))
        comms.threads.set_project("saved", str(new))
        agent = {"name": "Test", "identity": "project-resume", "short_name": "test",
                 "run_command": {"*": f"{sys.executable} -m agent_comms.acp"}, "protocol": "acp"}
        app = ToadApp(agent_data=agent, project_dir=str(old), agent_session_id="saved")
        async with app.run_test(size=(100, 35)) as pilot:
            async with asyncio.timeout(20):
                while not app.screen.query_one_optional(Conversation) or not app.screen.conversation.agent_ready:
                    await asyncio.sleep(.05)
            await pilot.pause()
            conversation = app.screen.conversation
            assert conversation.agent._connected_ok, conversation.agent.presentation.log_path.read_text()
            from runtime_fixture import reveal_project_tree
            await reveal_project_tree(app, pilot)
            assert app.screen.project_path == new
            assert conversation.project_path == new
            assert Path(app.screen.query_one(ProjectDirectoryTree).path) == new
            assert new.name in str(app.screen.query_one(ProjectDirectoryTree).root.label)
            async with asyncio.timeout(5):
                while psutil.Process(conversation.shell._pid).cwd() != str(new):
                    await asyncio.sleep(.05)
            assert conversation.working_directory == str(new)
            await conversation.shell.change_directory(str(old))
            await pilot.pause()
            assert conversation.project_path == new
            assert Path(conversation.prompt.current_directory.path) == new
            comms.threads.set_project("saved", str(old))
            async with asyncio.timeout(10):
                while app.screen.project_path != old:
                    await asyncio.sleep(.05)
            await pilot.pause()
            assert conversation.project_path == old
            assert Path(app.screen.query_one(ProjectDirectoryTree).path) == old
    print("project resume: saved project and external changes replace launch folder in every view")


if __name__ == "__main__":
    asyncio.run(main())
