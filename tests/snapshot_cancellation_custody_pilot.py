"""Actual SnapshotPublication cancellation and native history resource custody.

Run against the exact installed Sch215 pair. Native history widgets, source pages,
preparation workers and Textual teardown are real; no ACP/provider process starts.
This source/resource check is not physical or provider workflow acceptance.
"""
import asyncio
from importlib.metadata import distribution
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from textual.await_complete import AwaitComplete
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.transcript_publication import SnapshotPublication
from toad.widgets.transcript_history import TranscriptHistory


def resources(window):
    return [dict(identity=id(history), attached=history.is_attached,
                 state=type(history.state).__name__, coverage=history.state.reports_coverage,
                 source=history.committed_cursor.session_file)
            for history in window.histories]


async def cancelled(task):
    task.cancel()
    result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    assert isinstance(result[0], asyncio.CancelledError), result


async def exercise(view, pilot, old_page, new_page):
    old = TranscriptHistory(old_page)
    await view.contents.mount(old)
    await pilot.pause()
    assert old in view.window.histories and old.state.reports_coverage
    entered, release = asyncio.Event(), asyncio.Event()
    mount = view.contents.mount

    def held_mount(*widgets, **kwargs):
        actual = mount(*widgets, **kwargs)

        async def wait():
            await actual
            entered.set()
            await release.wait()

        return AwaitComplete(wait())

    phases = {}
    # Native mount has completed, but the real publication has not accepted it.
    with patch.object(view.contents, 'mount', held_mount):
        task = asyncio.create_task(SnapshotPublication(
            view.transcript, view, view.window, view.contents, new_page).publish())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            provisional = next(h for h in view.window.histories if h is not old)
            assert provisional.is_attached and not provisional.state.reports_coverage
            phases['before_acceptance_cancel'] = resources(view.window)
            await cancelled(task)
            assert not provisional.is_attached and provisional not in view.window.histories
            assert old.is_attached and old in view.window.histories
            phases['before_acceptance_completed'] = resources(view.window)
        finally:
            release.set()
            if not task.done():
                await cancelled(task)

    # Hold the old native history's actual Unmount handler. remove_children has
    # admitted Prune before the publishing caller reaches its optional await.
    entered, release = asyncio.Event(), asyncio.Event()
    unmount = TranscriptHistory.on_unmount

    async def held_unmount(history):
        if history is old:
            entered.set()
            await release.wait()
        unmount(history)

    with patch.object(TranscriptHistory, 'on_unmount', held_unmount):
        task = asyncio.create_task(SnapshotPublication(
            view.transcript, view, view.window, view.contents, new_page).publish())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            accepted = next(h for h in view.window.histories if h is not old)
            assert accepted.is_attached and accepted.state.reports_coverage
            assert not old.state.accepts_publication
            phases['accepted_retirement_held'] = resources(view.window)
            await cancelled(task)
            phases['accepted_caller_cancelled'] = resources(view.window)
            assert accepted.is_attached and accepted in view.window.histories
            # The independent teardown remains pending until its actual owner
            # completes Unmount, even though its publishing waiter has gone.
            release.set()
            async with asyncio.timeout(5):
                while old.is_attached or old in view.window.histories:
                    await pilot.pause(.01)
            assert set(view.window.histories) == {accepted}
            assert list(view.contents.query(TranscriptHistory)) == [accepted]
            phases['accepted_retirement_completed'] = resources(view.window)
        finally:
            release.set()
            if not task.done():
                await cancelled(task)
    return phases


async def main():
    artifacts = Path(os.environ['CUSTODY_EVIDENCE']).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    receipt = {'pins': {name: json.loads(distribution(name).read_text('direct_url.json'))
                       for name in ('batrachian-toad', 'agent-comms', 'textual')},
               'limit': 'Source/resource custody; no ACP, provider, original root or physical capture.'}
    with TemporaryDirectory(prefix='snapshot-custody-', dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        comms = Comms(root/'wire')
        comms.messaging.initialize_private_initial_protocol()
        pages = []
        for name in ('old', 'replacement'):
            source = root/f'{name}.jsonl'
            source.write_text(''.join(json.dumps({'type': 'message', 'message': {
                'role': 'assistant', 'content': f'## {name} saved row {i}\n\nNative resource custody.'}})
                + '\n' for i in range(6)))
            comms.registry.declare(Thread(name, frozenset(), str(root), session_file=str(source)))
            pages.append(comms.transcripts.thread_transcript_page(name))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            # Real ACP Agent resource, never started or configured for a model.
            # set_reactive avoids a startup watcher; this test admits no input.
            agent = Agent(root, AgentDefinition('custody', 'custody', {}), None)
            view.set_reactive(type(view).agent, agent)
            receipt['phases'] = await exercise(view, pilot, *pages)
            assert agent.process.process is None and agent.process.runner is None
            assert app._exception is None
        receipt['application_exit'] = 'normal'
    (artifacts/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('PASS: provisional cancellation removes only provisional resource; accepted caller cancellation preserves new source and independent old-resource retirement completes')


if __name__ == '__main__':
    asyncio.run(main())
