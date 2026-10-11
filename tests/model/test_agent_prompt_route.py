"""An ACP child keeps the root selection it was started with: implicit follows the default route, explicit stays put."""

from types import SimpleNamespace

import pytest

from support.routes import private_root, publish_route, select_root_by_default_route


@pytest.fixture
def routes(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    for name in ("CONFIG", "DATA", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    home = select_root_by_default_route(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    first, first_id = private_root(tmp_path / "first", tmp_path, "FIRST")
    second, second_id = private_root(tmp_path / "second", tmp_path, "SECOND")
    publish_route(home, first, first_id)
    return SimpleNamespace(home=home, project=project, first=first, second=second, second_id=second_id)


async def started_agent(project):
    from toad.acp.agent import Agent
    from toad.agent_schema import AgentDefinition

    agent = Agent(project, AgentDefinition("fake", "fake", {"*": "true"}), None)
    await agent.start()
    assert agent.process.runner is not None
    await agent.process.runner
    return agent


async def test_an_implicit_child_started_on_the_former_route_refuses_the_prompt_write_after_a_flip(routes, monkeypatch):
    agent = await started_agent(routes.project)
    assert agent.process.route_selection.implicit
    assert "AGENT_COMMS_ROOT" not in agent.process.env
    publish_route(routes.home, routes.second, routes.second_id)
    written = []
    agent.process.process = SimpleNamespace(stdin=SimpleNamespace(write=written.append))
    prompt = SimpleNamespace(body={"method": "session/prompt"}, body_json=b"{}")
    # A later explicit process override cannot turn the old-root child into an independent explicit-root writer.
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(routes.first))
    with pytest.raises(ValueError, match="route changed"):
        agent.send(prompt)
    assert not written, "stale implicit-root child prompt was written"


async def test_the_real_prompt_path_refuses_a_stale_implicit_child(routes, monkeypatch):
    agent = await started_agent(routes.project)
    publish_route(routes.home, routes.second, routes.second_id)
    written = []
    agent.process.process = SimpleNamespace(stdin=SimpleNamespace(write=written.append))
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(routes.first))
    with pytest.raises(ValueError, match="route changed"):
        async with agent.process.admitted_prompt(agent):
            agent.send(SimpleNamespace(body={"method": "session/prompt"}, body_json=b"{}"))
    assert not written


async def test_an_explicit_child_stays_on_its_root_after_the_parent_drops_its_override(routes, monkeypatch):
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(routes.first))
    agent = await started_agent(routes.project)
    monkeypatch.delenv("AGENT_COMMS_ROOT")
    assert not agent.process.route_selection.implicit
    assert agent.process.env["AGENT_COMMS_ROOT"] == str(routes.first)
    written = []
    agent.process.process = SimpleNamespace(stdin=SimpleNamespace(write=written.append))
    agent.send(SimpleNamespace(body={"method": "session/prompt"}, body_json=b"{}"))
    assert written == [b"{}\n"]
