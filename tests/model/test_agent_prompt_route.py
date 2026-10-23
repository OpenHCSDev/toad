"""An ACP child takes its application's explicit launch root, never an ambient override."""

import json
import sys
from dataclasses import replace

from support.agents import command
from toad.acp.agent import Agent


async def test_the_real_child_receives_the_selected_root_as_arguments_and_drops_the_environment_override(
        app_agents, tmp_path, monkeypatch):
    from agent_comms.launch_root import LaunchRoot

    output = tmp_path / "child-launch.json"
    program = (
        "import json,os,sys; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(json.dumps({'argv':sys.argv[2:],"
        "'root_env':os.environ.get('AGENT_COMMS_ROOT')}))"
    )
    definition = replace(command(sys.executable, "-c", program, str(output)), accepts_comms_root=True)
    agent = app_agents.agent(Agent, definition)
    selected = LaunchRoot.current()
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(tmp_path / "wrong-wire"))
    try:
        await agent.start()
        await agent.process.runner
        recorded = json.loads(output.read_text())
        assert recorded == {"argv": list(selected.arguments()), "root_env": None}
        assert agent.process.route_selection.root == selected.path
    finally:
        await agent.stop()
