"""Real channel updates and retained returns borrow the shared revision observer."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import threading
from xml.etree import ElementTree

from agent_comms.comms import Comms
from agent_comms.history_views import HistoryViews
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView, session_thread_name


async def until(predicate):
    async with asyncio.timeout(12):
        while not predicate():
            await asyncio.sleep(.02)


def painted_text(app):
    # The SVG is Textual's actual compositor output; decode its text entities.
    return ' '.join(''.join(ElementTree.fromstring(app.export_screenshot()).itertext()).split())


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/parent-comms-observation-20261006')
    reads = []
    code = HistoryViews.message_notifications.__code__

    def observe(frame, event, argument):
        if event == 'call' and frame.f_code is code:
            reads.append(asyncio_time())

    from time import monotonic as asyncio_time
    with tempfile.TemporaryDirectory(prefix='mounted-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'),
                          TOAD_TEST_ATTEMPT='comms-observed-source-20261006')
        comms = Comms(root / 'wire', private_initial_writes=True)
        for name in ('sender', 'reader', session_thread_name(root)):
            comms.registry.declare(Thread(name, frozenset({'alpha'}), str(root)))
        comms.messaging.initialize_private_initial_protocol()
        comms.messaging.send_initial_cohort('sender', '#alpha', 'INITIAL ORIGINAL ROW')
        app = ToadApp(project_dir=str(root))
        old_profile = sys.getprofile()
        old_thread_profile = threading.getprofile()
        sys.setprofile(observe)
        threading.setprofile(observe)
        try:
            async with app.run_test(size=(113, 34)) as pilot:
                await pilot.pause()
                owner = app.selected_mode
                await channel_target('#alpha').open(NavigationContext(app, owner, root, 'reader'))
                mode = app.selected_mode
                chat = app.selected_session.query_one(CommsChatView)
                history = chat.message_history
                await until(lambda: any(message.body == 'INITIAL ORIGINAL ROW' for message, _ in history.rows))
                await history.toggle_style()
                await until(lambda: bool(reads))
                idle_start = len(reads)
                await asyncio.sleep(2.2)
                idle_reads = len(reads) - idle_start
                comms.messaging.send_initial_cohort('sender', '#alpha', 'LIVE ORIGINAL UPDATE')
                await until(lambda: any(message.body == 'LIVE ORIGINAL UPDATE' for message, _ in history.rows))
                await until(lambda: 'LIVE ORIGINAL UPDATE' in painted_text(app))
                (scratch / 'live-update.svg').write_text(app.export_screenshot())
                await app.select_session(owner)
                parked_start = len(reads)
                comms.messaging.send_initial_cohort('sender', '#alpha', 'PARKED ORIGINAL UPDATE')
                await asyncio.sleep(1.2)
                assert len(reads) == parked_start, 'Parked channel read notification bodies'
                await app.select_session(mode)
                await until(lambda: any(message.body == 'PARKED ORIGINAL UPDATE' for message, _ in history.rows))
                await until(lambda: 'PARKED ORIGINAL UPDATE' in painted_text(app))
                (scratch / 'retained-return.svg').write_text(app.export_screenshot())
                assert app.selected_session.query_one(CommsChatView) is chat
                assert app._exception is None
                print({'result': 'PASS', 'idle_seconds': 2.2,
                       'actual_notification_reads_while_idle': idle_reads,
                       'live_update': True, 'parked_reads': 0,
                       'retained_return_update': True})
            await asyncio.get_running_loop().shutdown_default_executor()
        finally:
            sys.setprofile(old_profile)
            threading.setprofile(old_thread_profile)


if __name__ == '__main__':
    asyncio.run(main())
