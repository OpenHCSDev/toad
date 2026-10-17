"""Run the actual Toad CLI and observe its real P68 session lifetimes."""
import asyncio
import json
import os
from pathlib import Path
import signal

from toad.application_lifetime import ApplicationLifetime
from toad.cli import main

BASE = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')

async def painted(app):
    done = asyncio.Event()
    app.call_after_refresh(done.set)
    await done.wait()

async def connected_agent(view):
    await view.wait_content_ready()
    conversation = view.presentation.widget
    available = asyncio.Event()
    def agent_changed(agent):
        if agent is not None:
            available.set()
    view.watch(conversation, 'agent', agent_changed, init=True)
    await asyncio.wait_for(available.wait(), 90)
    agent = conversation.agent
    await asyncio.wait_for(agent.session.settled.wait(), 90)
    if not agent.ready:
        raise RuntimeError(str(agent.session.disposition.current_failure()))
    return agent

async def observe(app):
    failed_mode = app.selected_mode
    failed_view = app.session_navigation.source(failed_mode)
    failed = await connected_agent(failed_view)
    healthy_mode = await app.thread_navigation.open(owner_mode=failed_mode,
        project_path=BASE / 'project-b', target='p68-healthy')
    healthy_view = app.session_navigation.source(healthy_mode)
    healthy = await connected_agent(healthy_view)
    await painted(app)
    ready = {'app_pid': os.getpid(), 'failed_mode': failed_mode, 'healthy_mode': healthy_mode,
             'failed_ready': failed.ready, 'healthy_ready': healthy.ready,
             'failed_acp_pid': failed.process.process.pid,
             'healthy_acp_pid': healthy.process.process.pid}
    (BASE / 'ui-ready.json').write_text(json.dumps(ready, indent=2))

    async def trigger(reader, writer):
        await reader.readexactly(1)
        plan = failed.session.load_plan
        owner = await app.preparation.run_thread(
            app.coordination_access.service.registry.require, 'p68-failed')
        pidfd = os.pidfd_open(owner.pid)
        if not owner.process_identity.alive():
            os.close(pidfd)
            raise RuntimeError('Owned process identity changed before the requested kill')
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        os.close(pidfd)
        await failed.session.reconnect(plan)
        await app.select_session(failed_mode)
        await painted(app)
        failure = failed.session.disposition.current_failure()
        result = dict(ready, killed_pid=owner.pid,
            failed_connected=failed.session.connected, healthy_ready_after=healthy.ready,
            reason=None if failure is None else {'message': failure.message, 'details': failure.details})
        (BASE / 'ui-failed.json').write_text(json.dumps(result, indent=2))
        writer.write(json.dumps(result).encode() + b'\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        server.close()

    server = await asyncio.start_unix_server(trigger, path=str(BASE / 'ui.sock'))
    await server.wait_closed()


def started(lifetime):
    app = lifetime.app
    def begin():
        task = asyncio.create_task(observe(app), name='p68-live-observation')
        def finished(task):
            if not task.cancelled() and (error := task.exception()) is not None:
                (BASE / 'ui-observer-error.json').write_text(json.dumps(
                    {'type': type(error).__name__, 'error': str(error)}, indent=2))
        task.add_done_callback(finished)
    app.call_after_refresh(begin)

if __name__ == '__main__':
    ApplicationLifetime.observe_next_start(started)
    main()
