from toad.agent_schema import AgentDefinition
"""Session boundary publications retain actual process and binding custody."""
import asyncio
from toad import jsonrpc
from toad.acp import api
from toad.acp.agent import Agent


def test_pending_handshake_authentication_and_mode_reject_retired_binding(tmp_path, monkeypatch):
    async def run():
        for method, api_name, result, args in (
            ('initialize', 'initialize', {'agentCapabilities': {'loadSession': True}, 'authMethods': [{'id': 'late'}]}, ()),
            ('authenticate', 'authenticate', {}, ('terminal',)),
            ('set_mode', 'session_set_mode', {}, ('late',)),
            ('new', 'session_new', {'sessionId': 'late-new'}, ()),
            ('load', 'session_load', {}, ()),
        ):
            agent = Agent(tmp_path, AgentDefinition.decode({'identity': 'session', 'name': 'session', 'run_command': {'*': 'true'}}), 'original')
            entered, release = asyncio.Event(), asyncio.Event()
            class Pending:
                async def wait(self):
                    entered.set()
                    await release.wait()
                    return result
            monkeypatch.setattr(api, api_name, lambda *a, **k: Pending())
            binding = agent.controller.session
            task = asyncio.create_task(getattr(agent.session, method)(*args))
            await entered.wait()
            agent.session_id = 'replacement'
            agent.session_id = 'original'
            assert agent.controller.session is not binding
            release.set()
            try:
                response = await task
            except jsonrpc.InvalidParams:
                pass
            else:
                # Mode's existing public failure contract returns actionable feedback.
                assert method == 'set_mode' and 'retired session' in response
            assert agent.session_id == 'original'
            assert not agent.session.capabilities.load_session
            assert not agent.presentation.auth_methods
            assert not agent.session.ready
            await agent.stop()
    asyncio.run(run())
