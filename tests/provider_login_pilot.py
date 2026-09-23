"""ACP terminal auth reuses ActionModal/CommandPane and refreshes models in place."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import psutil
from agent_comms import wire
from runtime_fixture import ToadApp
from toad.screens.action_modal import ActionModal
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.command_pane import CommandPane


async def until(predicate):
    async with asyncio.timeout(20):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-auth-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        auth_dir = root / "pi"
        auth_dir.mkdir()
        (auth_dir / "auth.json").write_text("{}")
        pid_file = root / "login.pid"
        stub = root / "pi-auth-fixture"
        stub.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
from pathlib import Path
auth = Path(os.environ["PI_CODING_AGENT_DIR"]) / "auth.json"
if "--mode" not in sys.argv:
    assert "AGENT_COMMS_THREAD" not in os.environ
    assert "PI_AGENT_ID" not in os.environ
    Path(os.environ["TEST_LOGIN_PID"]).write_text(str(os.getpid()))
    print("Native Pi login controls: type authorize", flush=True)
    if sys.stdin.readline().strip() == "authorize":
        auth.write_text(json.dumps({"openai-codex": {"type": "oauth", "access": "fixture", "refresh": "fixture", "expires": 9999999999999}}))
        print("Login complete", flush=True)
        sys.exit(0)
    sys.exit(1)
for line in sys.stdin:
    request = json.loads(line)
    models = [{"provider": "test", "id": "base"}]
    if "openai-codex" in json.loads(auth.read_text()):
        models.append({"provider": "openai-codex", "id": "subscription"})
    print(json.dumps({"id": request.get("id"), "type": "response", "command": request["type"],
                      "success": True, "data": {"models": models}}), flush=True)
""")
        stub.chmod(0o755)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN=str(stub),
            AGENT_COMMS_AGENT_ARGS="--model test/base",
            PI_CODING_AGENT_DIR=str(auth_dir),
            TEST_LOGIN_PID=str(pid_file),
        )
        os.environ.pop("AGENT_COMMS_AGENT_MODELS", None)
        agent = {
            "name": "Agent Comms",
            "identity": "auth-test",
            "short_name": "auth-test",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
            "protocol": "acp",
        }
        app = ToadApp(agent_data=agent, project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await until(
                lambda: getattr(app.screen, "conversation", None) is not None
                and app.screen.conversation.agent_ready
            )
            conversation = app.screen.conversation
            assert any(
                m["id"] == "pi-login-openai-codex"
                for m in conversation.agent.auth_methods
            )
            await conversation.post(AgentResponse("Preserve this existing transcript"))
            transcript = root / "session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": "Preserve this existing transcript",
                        },
                    }
                )
            )
            comms = wire(root / "wire")
            comms.attach_session("project", str(transcript))
            conversation.prompt.text = "Preserve this draft"

            async def open_login():
                await conversation.slash_command("/login")
                await until(lambda: isinstance(app.screen, ContextMenu))
                await pilot.pause()
                button = next(
                    item
                    for item in app.screen.query(ContextMenuItem)
                    if item.action == "pi-login-openai-codex"
                )
                assert await pilot.click(button)
                await until(
                    lambda: isinstance(app.screen, ActionModal) and pid_file.exists()
                )
                await pilot.pause()

            await open_login()
            assert app.screen.query_one(CommandPane).has_focus
            await pilot.press(*"authorize", "enter")
            await until(lambda: not isinstance(app.screen, ActionModal))
            await until(lambda: "openai-codex/subscription" in conversation.models)
            assert sum(thread.role.executable for thread in comms.registry.all_threads().values()) == 1
            assert conversation.prompt.text == "Preserve this draft"
            assert (
                sum(
                    "Preserve this existing transcript" in item.source
                    for item in conversation.query(AgentResponse)
                )
                == 1
            )
            pid_file.unlink()
            await open_login()
            login_pid = int(pid_file.read_text())
            assert await pilot.click("#cancel")
            await until(lambda: not isinstance(app.screen, ActionModal))
            assert not psutil.pid_exists(login_pid)
            pid_file.unlink()
            await open_login()
            login_pid = int(pid_file.read_text())
        assert not psutil.pid_exists(
            login_pid
        ), "App shutdown must also close the login subprocess"
    print(
        "provider login: existing modal/terminal, ACP reconnect, model refresh, transcript preservation, cancellation and shutdown passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
