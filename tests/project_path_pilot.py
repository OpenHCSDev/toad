"""Real ACP project change, automatic continuation, and synchronized Toad views."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import psutil
from agent_comms import wire
from toad import messages
from runtime_fixture import ToadApp
from toad.db import DB
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.project_directory_tree import ProjectDirectoryTree


async def until(predicate):
    async with asyncio.timeout(20):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-project-") as directory:
        root = Path(directory)
        old = root / "old-project"
        new = root / "new project"
        old.mkdir()
        new.mkdir()
        (old / "OLD.txt").write_text("old project")
        (new / "NEW.txt").write_text("new project")
        session_file = old / "session.jsonl"
        session_file.write_text("")
        calls = root / "calls.jsonl"
        stub = root / "pi-project"
        stub.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
from pathlib import Path
from agent_comms import wire
def emit(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    command = json.loads(line)["type"]
    data = {}
    if command == "get_state":
        data = {"sessionFile": os.environ["TEST_SESSION"], "model": {"provider": "test", "id": "model"}}
    elif command == "prompt":
        with open(os.environ["TEST_CALLS"], "a") as out:
            out.write(json.dumps({"cwd": os.getcwd(), "session": os.environ["TEST_SESSION"]}) + "\\n")
        if os.getcwd() != os.environ["TEST_PROJECT"]:
            emit({"type": "tool_execution_start", "toolCallId": "project", "toolName": "comms_set_project", "args": {"path": os.environ["TEST_PROJECT"]}})
            result = wire().set_project_self(os.environ["TEST_PROJECT"])
            emit({"type": "tool_execution_end", "toolCallId": "project", "toolName": "comms_set_project", "isError": False, "result": {"content": [{"type": "text", "text": result.current}]}})
        else:
            emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Verified new project: " + os.getcwd()}})
        emit({"type": "agent_settled"})
    emit({"type": "response", "command": command, "success": True, "data": data})
""")
        stub.chmod(0o755)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN=str(stub),
            AGENT_COMMS_AGENT_ARGS="--provider test --model model",
            AGENT_COMMS_AGENT_MODELS="test/model",
            TEST_SESSION=str(session_file),
            TEST_PROJECT=str(new),
            TEST_CALLS=str(calls),
        )
        comms = wire(root / "wire")
        agent = {
            "name": "Agent Comms",
            "identity": "project-test",
            "short_name": "project-test",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
            "protocol": "acp",
        }
        app = ToadApp(agent_data=agent, project_dir=str(old))
        async with app.run_test(size=(120, 40)) as pilot:
            await until(
                lambda: getattr(app.screen, "conversation", None) is not None
                and app.screen.conversation.agent_ready
            )
            mode = app.current_mode
            main_screen = app.screen
            from runtime_fixture import reveal_project_tree
            await reveal_project_tree(app, pilot)
            conversation = main_screen.conversation
            owner_pid = comms.registry.require("old-project").pid
            chat_mode = await app.open_comms_session(
                owner_mode=mode,
                project_path=old,
                me="old-project",
                target="#any",
                kind="irc",
            )
            chat_screen = app.screen
            await app.switch_mode(mode)
            conversation.post_message(
                messages.UserInputSubmitted("Switch project and verify it")
            )
            await until(
                lambda: any(
                    "Verified new project" in block.source
                    for block in conversation.query(AgentResponse)
                )
            )
            await until(lambda: main_screen.project_path == new)
            await pilot.pause()
            assert conversation.project_path == new
            assert conversation.working_directory == str(new)
            assert conversation.agent.project_root_path == new
            assert Path(main_screen.query_one(ProjectDirectoryTree).path) == new
            assert conversation.prompt.path_search.root == new
            assert not conversation.prompt.has_class("-working-directory-out-of-bounds")
            await until(
                lambda: psutil.Process(conversation.shell._pid).cwd() == str(new)
            )
            saved = await DB().session_get(conversation.agent.session_pk)
            meta = json.loads(saved["meta_json"])
            assert (
                meta["cwd"] == str(new)
                and meta["agent_data"]["identity"] == "project-test"
            )
            assert chat_screen.project_path == new
            assert chat_screen.query_one(CommsChatView).working_directory == str(new)
            assert [
                json.loads(line)["cwd"] for line in calls.read_text().splitlines()
            ] == [str(old), str(new)]
            thread = comms.registry.require("old-project")
            assert thread.worktree == str(new) and thread.pid == owner_pid
            assert thread.session_file == str(session_file)
            assert (
                sum(thread.role.executable for thread in comms.registry.all_threads().values()) == 1
                and app.session_tracker.session_count == 1
            )
            assert (
                await app.open_comms_session(
                    owner_mode=mode,
                    project_path=new,
                    me=thread.name,
                    target="#any",
                    kind="irc",
                )
                == chat_mode
            )
            await app.switch_mode(mode)
            await conversation.slash_command(f'/project "{old}"')
            await until(lambda: main_screen.project_path == old)
            await until(
                lambda: psutil.Process(conversation.shell._pid).cwd() == str(old)
            )
            assert comms.registry.require("old-project").pid == owner_pid
    print(
        "project changes: same owner/session, automatic continuation, file tree, prompt, shell, saved state and IRC views passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
