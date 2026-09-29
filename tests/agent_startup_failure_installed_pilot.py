"""Real installed Toad rendering of terminal ACP startup outcomes, no providers."""
import asyncio
from importlib.resources import files
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.widgets.conversation import Conversation, ThreadLoading


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def until(pilot, predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await pilot.pause(.02)


async def case(root, kind):
    code = "import sys;sys.stdin.readline()"
    data = {'name': 'Startup proof', 'identity': 'startup-proof', 'short_name': 'proof',
            'protocol': 'acp', 'run_command': {'*': shlex.join((sys.executable, '-c', code))}}
    original = Agent.acp_initialize

    async def error(self):
        raise RuntimeError('SOURCE_INITIALIZATION_FAILURE')

    app = InstalledApp(agent_data=data, project_dir=str(root))
    with patch.object(Agent, 'acp_initialize', error if kind == 'error' else original):
        async with app.run_test(size=(139, 25)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.query_one(Conversation)
            await until(pilot, lambda: view.agent is not None)
            agent = view.agent
            await until(pilot, agent.session_ready_event.is_set)
            await until(pilot, lambda: view._agent_fail and not view.query(ThreadLoading))
            expected = ('SOURCE_INITIALIZATION_FAILURE' if kind == 'error'
                        else 'ACP process closed')
            window = view.window.region
            def painted():
                frame = '\n'.join(strip.crop(window.x, window.right).text
                    for strip in app.screen._compositor.render_strips()[window.y:window.bottom])
                return expected in frame
            try:
                await until(pilot, painted)
            except TimeoutError:
                print('FAILURE_FRAME', '\n'.join(strip.text for strip in app.screen._compositor.render_strips()), flush=True)
                print('GEOMETRY', [(type(node).__name__, str(node.region)) for node in view.contents.walk_children()], flush=True)
                raise
            await until(pilot, lambda: agent.process.process is None)
            assert not agent.ready
            assert app._exception is None
            print('ACTUAL_STARTUP_FAILURE_PAINTED_AND_RETIRED', kind, flush=True)
            await agent.stop()


async def main():
    with TemporaryDirectory(prefix='startup-failure-', dir=os.environ['TMPDIR']) as directory:
        root = Path(directory)
        with patch.dict(os.environ, {'AGENT_COMMS_ROOT': str(root / 'wire'),
                                    'XDG_STATE_HOME': str(root / 'state'),
                                    'XDG_CONFIG_HOME': str(root / 'config'),
                                    'XDG_DATA_HOME': str(root / 'data')}):
            for kind in ('eof', 'error'):
                await case(root, kind)


if __name__ == '__main__':
    asyncio.run(main())
