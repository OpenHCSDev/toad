"""Actual SnapshotPublication cancellation and native history resource custody.

Run against an exact installed source-publication pair. Native history widgets, source pages,
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
            task.cancel()
            await pilot.pause(.05)
            phases['accepted_caller_cancelled'] = resources(view.window)
            assert accepted.is_attached and accepted in view.window.histories
            # Teardown remains pending until its actual owner completes Unmount,
            # even after cancellation of the publishing waiter is requested.
            release.set()
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
            assert isinstance(result[0], asyncio.CancelledError), result
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


async def exercise_preprune(view, pilot, old_page, new_page, *, checkpoint=False):
    """Cancel the accepted publication before its native Prune is admitted."""
    from toad.live_output import ResponseStream
    from toad.transcript_publication import CheckpointPublication

    old = TranscriptHistory(old_page)
    await view.contents.mount(old)
    await pilot.pause()
    block = None
    if checkpoint:
        # Real live output resource already represented in the saved native page.
        # The real settled-turn/source capture decides its retirement candidacy.
        block = await view.output.append(ResponseStream(), new_page.events[0].text)
        view.transcript.dirty = view.transcript.checkpoint_required = True
        view.window.anchor()
        view.prompt.focus()
    entered = asyncio.Event()
    retire = view.output.retire_presentations
    proof = {'kind': 'checkpoint' if checkpoint else 'snapshot'}

    async def observe_retirement(candidates):
        proof['retirement_candidate_ids'] = [id(candidate) for candidate in candidates]
        proof['old_native_history_covered'] = old in candidates
        if checkpoint:
            proof['actual_stream_block_covered'] = block in candidates
            assert block in candidates, 'Source did not cover the original live stream'
        entered.set()
        await retire(candidates)

    publication = (CheckpointPublication(view.transcript, view, view.window, view.contents)
                   if checkpoint else SnapshotPublication(
                       view.transcript, view, view.window, view.contents, new_page))
    task = None
    try:
        with patch.object(view.output, 'retire_presentations', observe_retirement):
            async with view.output.lock:
                task = asyncio.create_task(publication.publish())
                await asyncio.wait_for(entered.wait(), 5)
                proof['accepted_before_cancel'] = resources(view.window)
                # The real output owner is held here. Its paged finish must
                # still be able to acquire both original source/tree locks;
                # accepted retirement waits outside them, never in opposition.
                async with asyncio.timeout(5):
                    async with view.window.history_lock:
                        async with view.window.lock:
                            proof['source_and_tree_locks_available_during_output_join'] = True
                assert not old.display
                task.cancel()
                await pilot.pause(.05)
                proof['cancelled_while_output_lock_held'] = resources(view.window)
                proof['publishing_waiter_done_while_locked'] = task.done()
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
            proof['result'] = type(result[0]).__name__
            assert isinstance(result[0], asyncio.CancelledError), result
            await pilot.pause(.1)
            proof['after_output_lock_release'] = resources(view.window)
            proof['old_still_attached'] = old.is_attached
            proof['old_still_registered'] = old in view.window.histories
            if checkpoint:
                proof['stream_block_still_attached'] = block.is_attached
                proof['stream_association_remaining'] = ResponseStream in view.output.streams
            return proof
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


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
            entries = [{'type': 'session', 'id': name, 'version': 3, 'cwd': str(root)}]
            for i in range(6):
                entries.append({'type': 'message', 'id': f'{name}-{i}',
                    'parentId': entries[-1]['id'], 'message': {
                        'role': 'assistant', 'stopReason': 'stop',
                        'content': [{'type': 'text', 'text':
                            f'## {name} saved row {i}\n\nNative resource custody.'}]}})
            source.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
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
            case = os.environ.get('CUSTODY_CASE', 'mount_and_prune')
            if case == 'mount_and_prune':
                receipt['phases'] = await exercise(view, pilot, *pages)
            else:
                if case == 'covered_checkpoint':
                    from agent_comms.acp_extension import CoordinationChangedUpdate
                    thread = comms.registry.require('replacement')
                    agent.coordination = CoordinationChangedUpdate(
                        thread.incarnation, str(root/'wire'), os.getpid(), str(root),
                        None, None, thread.name, None)
                    view.set_reactive(type(view).agent_ready, True)
                receipt['phases'] = await exercise_preprune(
                    view, pilot, *pages, checkpoint=case == 'covered_checkpoint')
            assert agent.process.process is None and agent.process.runner is None
            assert app._exception is None
        receipt['application_exit'] = 'normal'
    (artifacts/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    if case != 'mount_and_prune':
        assert not receipt['phases']['old_still_attached'], 'Accepted cancellation abandoned old native history'
        assert not receipt['phases']['old_still_registered'], 'Accepted cancellation retained competing native histories'
        if case == 'covered_checkpoint':
            assert not receipt['phases']['stream_block_still_attached'], 'Covered original stream block survived retirement'
            assert not receipt['phases']['stream_association_remaining'], 'Retired source retained its stream association'
    print('PASS: original source and native resource retirement completes after cancellation', case)


if __name__ == '__main__':
    asyncio.run(main())
