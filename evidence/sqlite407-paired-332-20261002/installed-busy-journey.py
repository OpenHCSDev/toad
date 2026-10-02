"""One installed App/source journey with the existing canonical private fixture.

No provider/ACP process, SQL result substitution, publication subclass, or new
observer. HeadlessDriver renders actual widgets; parent owns configured LinuxDriver
and native/provider acceptance after publication.
"""
from pathlib import Path
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CORE = Path('/home/ts/wt/comms-goal-ledger-schema-carry-20261002')
sys.path.insert(0, str(CORE / 'tests'))
sys.path.insert(0, str(REPO / 'tests'))
from test_coordinated_runtime import _root
from comms_boundary_fixture import attach_registered_coordination
from agent_comms.assignment_states import IgnoredAssignment
from agent_comms.bus_publication import stable_thread_lookup
from agent_comms.coordinator import Coordination
from agent_comms.notification_assignment import NotificationAssignment
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.transcript_publication import CanonicalSourcePublication, HandlingPublication
from toad.transcript_state import WorkingTranscript
from toad.widgets.message_notifications import MessageNotifications

ORIGIN = time.monotonic()
EVENTS = []

def record(phase, **facts):
    EVENTS.append({'phase':phase,'elapsed':time.monotonic()-ORIGIN,**facts})
    (OUT / 'events.json').write_text(json.dumps(EVENTS,indent=2)+'\n')

async def wait_for(pilot, predicate, description):
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        if predicate(): return
        await pilot.pause(.05)
    raise AssertionError(description)

def frame(app, name):
    (OUT / (name+'.svg')).write_text(app.export_screenshot())
    rows = [strip.text for strip in app.screen._compositor.render_strips()]
    (OUT / (name+'.txt')).write_text('\n'.join(rows)+'\n')
    return '\n'.join(rows)

async def main():
    # The existing fixture's sealed private protocol requires this owned short
    # /var/tmp root; it has no saved/uncertain or provider input to preserve.
    with tempfile.TemporaryDirectory(prefix='ac-ui407-',dir='/var/tmp') as directory:
        fixture = Path(directory)
        root, _root_id, comms, initial, _people = _root(fixture)
        os.environ.update(AGENT_COMMS_ROOT=str(root),XDG_CONFIG_HOME=str(fixture/'config'),
                          XDG_STATE_HOME=str(fixture/'state'),XDG_DATA_HOME=str(fixture/'data'))
        app = ToadApp(project_dir=str(fixture))
        async with app.run_test(size=(120,40)) as pilot:
            await app.screen.prepare_navigation()
            await app.screen.layout_navigation()
            view = app.selected_session.conversation
            agent = Agent(fixture, AgentDefinition.decode({'name':'Source','identity':'source',
                'short_name':'source','run_command':{'*':'true'},'protocol':'acp'}),'sender')
            attach_registered_coordination(agent, root, 'sender')
            view.agent = agent
            await pilot.pause()
            assert await view.transcript.publish(CanonicalSourcePublication)
            await wait_for(pilot,lambda:bool(view.transcript.histories),'Initial original history did not mount')
            await view.transcript.publish(HandlingPublication)
            await pilot.pause(.2)
            assert initial.message.body in frame(app,'before')
            histories = tuple(view.transcript.histories)
            history = histories[0]
            lookup = stable_thread_lookup(comms.registry.require('beta').created_at)
            original = NotificationAssignment.select(root,'w.wire_seq=? AND w.recipient_lookup=?',
                                                       (initial.message.seq,lookup))[0].assignment
            notifications = tuple(view.contents.query(MessageNotifications))
            assert notifications and any('Pending' in str(body.title) for body in notifications)
            wire_before = comms.bus.log.path.read_bytes()
            # Only the original canonical assignment changes. No copied read or
            # local handling authority supplies the new outcome to the widgets.
            with Coordination(str(root/'coordination.sqlite3')) as writer:
                writer.assignments.transition_preengagement(original.assignment_id,IgnoredAssignment,
                                                            expected_revision=original.revision)
                with writer.session.irreversible_admission():
                    handling = view.transcript.capture(HandlingPublication)
                    assert not await handling.publish()
                    assert view.transcript.source_requests.pending.qsize()==1
                    assert tuple(view.transcript.histories)==histories
                    assert any('Pending' in str(body.title) for body in notifications)
                    # End's real source-work owner must remain suspended across
                    # unavailable reads. This calls the same declared latest
                    # operation used by HistoryWindow's End action.
                    history.request_latest()
                    await wait_for(pilot,lambda:isinstance(history.state,WorkingTranscript),
                                   'Latest operation did not retain its admission')
                    operation = history.state
                    await pilot.pause(.35)
                    assert history.state is operation
                    assert not operation.accepts_source_work
                    assert initial.message.body in frame(app,'during-busy')
                    assert app._exception is None
                    record('busy-retained', original_message_id=initial.message.message_id,
                           original_sequence=initial.message.seq,
                           pending_source_requests=view.transcript.source_requests.pending.qsize(),
                           history_state=type(history.state).__name__)
                record('exclusive-released')
            # No refresh/publication call, input, direct signal publication or
            # new timer after release. Existing coordination_observed owns relief.
            await wait_for(pilot,lambda:any('Ignored' in str(body.title) for body in view.contents.query(MessageNotifications)),
                           'Original recipient handling did not publish after release')
            await wait_for(pilot,lambda:not isinstance(history.state,WorkingTranscript),
                           'Original latest admission did not complete after release')
            assert initial.message.body in frame(app,'after')
            assert comms.bus.log.path.read_bytes()==wire_before
            assert not view.transcript.source_requests.pending.qsize()
            assert app._exception is None
            record('observer-published',history_state=type(history.state).__name__,
                   handling=[str(body.title) for body in view.contents.query(MessageNotifications)],
                   wire_sha256=hashlib.sha256(wire_before).hexdigest())
            await view.transcript.close()
            await pilot.pause()
            assert app._exception is None
            record('retired-no-worker-failure')
        assert app._exception is None
    record('private-fixture-cleaned')
    (OUT/'receipt.json').write_text(json.dumps({'status':'PASS','driver':'HeadlessDriver',
        'scope':'Installed actual App/Agent/canonical wire/SQL/source/handling; no ACP or native/provider process',
        'refresh_after_release':False,'new_input':False,'provider_calls':0,'events':EVENTS},indent=2)+'\n')

if __name__=='__main__':
    try: asyncio.run(main())
    except BaseException as error:
        record('failed',error_type=type(error).__name__,error=str(error))
        raise
