"""Installed source-boundary fault injection, with real mounted Textual delivery."""
import asyncio
from pathlib import Path
from textual import on
from textual.app import App
from toad.agent import AgentFail
from toad.acp.agent import Agent
from toad.render_processes import RenderProcessPool

class FailureDelivery(App):
    def __init__(self):
        super().__init__()
        self.failure = None
        self.delivered = asyncio.Event()
        self.render_processes = RenderProcessPool()

    @on(AgentFail)
    def failed(self, message):
        self.failure = message
        self.delivered.set()

async def main():
    app = FailureDelivery()
    agent = Agent(Path.cwd(), {'identity': 'boundary-proof', 'name': 'Boundary proof', 'run_command': {'*': ''}}, None, None)
    async with app.run_test() as pilot:
        agent.attach_surface(app)
        async def fail():
            raise RuntimeError('Message is missing attributes; did you forget to call super().__init__() ?')
        agent.run = fail
        agent._connected_ok = True
        await agent.controller.initialize()
        await asyncio.wait_for(app.delivered.wait(), 3)
        assert app.failure.message == 'Agent initialization failed'
        assert app.failure.details.startswith('RuntimeError: Message is missing attributes')
        assert agent.session_ready_event.is_set() and not agent._connected_ok
        app.delivered.clear()
        async def blocked():
            await asyncio.Event().wait()
        agent.run = blocked
        task = asyncio.create_task(agent.controller.initialize())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('Cancellation was swallowed')
        await pilot.pause()
        assert not app.delivered.is_set()
        assert app._exception is None
        await app.render_processes.aclose()
    print('PASS: installed source initialization exception produces mounted AgentFail; cancellation remains cancellation')
    print('Fault-injected internal RuntimeError; no native/provider coverage claimed')

if __name__ == '__main__':
    asyncio.run(main())
