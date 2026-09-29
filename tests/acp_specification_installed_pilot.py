"""Continuous installed SDK stdio -> physical permission -> RPC -> painted reply."""
import asyncio
from importlib.resources import files
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from sidebar_retirement_pilot import until
from toad.agent_schema import AgentDefinition
from toad import messages
from toad.screens.permissions import PermissionsScreen
from toad.widgets.tool_call import ToolCall


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


def frame(app):
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


async def main():
    with TemporaryDirectory(prefix='sdk-contract-', dir=os.environ['TMPDIR']) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'), XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'))
        definition = AgentDefinition.decode({'name': 'SDK RPC acceptance', 'identity': 'sdk-rpc',
            'run_command': {'*': shlex.join([sys.executable, str(Path(__file__).with_name('acp_specification_server.py'))])}})
        app = InstalledApp(project_dir=str(root), agent_data=definition)
        async with app.run_test(size=(130, 44)) as pilot:
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None and view.agent_ready)
            agent = view.agent
            try:
                await view.submit_input(messages.UserInputSubmitted('SDK_SPECIFICATION_JOURNEY'))
                await until(pilot, lambda: isinstance(app.screen, PermissionsScreen))
                await until(pilot, lambda: 'old SDK content' in frame(app) and 'new SDK content' in frame(app))
                assert 'Allow SDK edit' in frame(app)
                await pilot.press('a')
                await until(pilot, lambda: (root / 'rpc-receipt.json').exists())
                await until(pilot, lambda: 'SDK_RPC_JOURNEY_COMPLETE' in frame(app))
                tool = view.query_one(ToolCall)
                assert tool.tool_call.completed
                assert (root / 'sdk-file.txt').read_text() == 'new SDK content'
                assert app._exception is None
                evidence = Path(os.environ['L0A_EVIDENCE'])
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / 'rpc-receipt.json').write_text((root / 'rpc-receipt.json').read_text())
                (evidence / 'rpc-journey.svg').write_text(app.export_screenshot())
                (root / 'rpc-painted').touch()
                await until(pilot, lambda: view.agent_ready)
                assert not agent.permissions.pending
                print('ACTUAL_INSTALLED_SDK_FILES_PERMISSION_TERMINALS_SIGNAL_TOOL_UPDATE_AND_REPLY_PAINTED', flush=True)
            finally:
                (root / 'rpc-painted').touch()
                await agent.stop()
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == '__main__':
    asyncio.run(main())
