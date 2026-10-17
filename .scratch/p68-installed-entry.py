"""Real Toad CLI: open two threads, kill one ACP child, reconnect it into a failure."""
import asyncio, json, os, signal, sys
from pathlib import Path

from toad.application_lifetime import ApplicationLifetime
from toad.cli import main

BASE = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
OUT = BASE / 'run3'

async def painted(app):
    done = asyncio.Event()
    app.call_after_refresh(done.set)
    await done.wait()

async def connected_agent(view):
    await view.wait_content_ready()
    conversation = view.presentation.widget
    available = asyncio.Event()
    view.watch(conversation, 'agent', lambda a: a is not None and available.set(), init=True)
    await asyncio.wait_for(available.wait(), 90)
    agent = conversation.agent
    await asyncio.wait_for(agent.session.settled.wait(), 90)
    if not agent.ready:
        raise RuntimeError(str(agent.session.disposition.current_failure()))
    return agent

def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, default=str))

def reason(agent):
    f = agent.session.disposition.current_failure()
    return None if f is None else {'message': f.message, 'details': f.details}

async def observe(app):
    failed_mode = app.selected_mode
    failed = await connected_agent(app.session_navigation.source(failed_mode))
    healthy_mode = await app.thread_navigation.open(owner_mode=failed_mode,
        project_path=BASE / 'project-b', target='p68-healthy')
    healthy = await connected_agent(app.session_navigation.source(healthy_mode))
    await painted(app)
    acp_pid = failed.process.process.pid
    healthy_pid = healthy.process.process.pid
    import toad, agent_comms
    ready = {'toad_file': toad.__file__, 'agent_comms_file': agent_comms.__file__, 'sys_path': sys.path, 'app_pid': os.getpid(), 'failed_mode': failed_mode, 'healthy_mode': healthy_mode,
             'failed_acp_pid': acp_pid, 'healthy_acp_pid': healthy_pid,
             'failed_ready': failed.ready, 'healthy_ready': healthy.ready}
    write('ready.json', ready)
    await asyncio.sleep(3)
    plan = failed.session.load_plan
    os.kill(acp_pid, signal.SIGKILL)
    for _ in range(100):
        if failed.session.disposition.current_failure() is not None:
            break
        await asyncio.sleep(0.1)
    after_kill = reason(failed)
    project = BASE / 'project-a'
    moved = BASE / 'project-a.moved'
    project.rename(moved)
    escaped = None
    try:
        await failed.session.reconnect(plan)
    except BaseException as error:
        escaped = f'{type(error).__name__}: {error}'
    finally:
        moved.rename(project)
    await app.select_session(failed_mode)
    await painted(app)
    label = app.session_navigation.source(failed_mode).query_one('#session-opening')
    result = dict(ready, after_kill=after_kill, after_reconnect=reason(failed),
                  escaped_from_reconnect=escaped, label_text=str(label.render()),
                  label_display=label.display, failed_connected=failed.session.connected,
                  healthy_ready=healthy.ready, healthy_reason=reason(healthy),
                  healthy_acp_alive=Path(f'/proc/{healthy_pid}').exists())
    write('failed.json', result)
    await asyncio.sleep(4)
    await app.select_session(healthy_mode)
    await painted(app)
    hl = app.session_navigation.source(healthy_mode).query_one_optional('#session-opening')
    write('healthy.json', {'healthy_ready': healthy.ready, 'healthy_reason': reason(healthy),
        'healthy_label_display': None if hl is None else hl.display,
        'healthy_acp_alive': Path(f'/proc/{healthy_pid}').exists(),
        'app_alive': True})

def started(lifetime):
    app = lifetime.app
    def begin():
        task = asyncio.create_task(observe(app), name='p68-reconnect-observation')
        def finished(task):
            if not task.cancelled() and (error := task.exception()) is not None:
                write('observer-error.json', {'type': type(error).__name__, 'error': str(error)})
        task.add_done_callback(finished)
    app.call_after_refresh(begin)

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    ApplicationLifetime.observe_next_start(started)
    main()
