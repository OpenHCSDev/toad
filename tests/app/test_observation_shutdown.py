"""Unmount ends interest, not the real observer's already-acquired reads."""

import asyncio
import sys

from agent_comms.ui_model.observation import ObservationProcess, ObserveNotifications, ReadNotifications
from toad.comms_root import AnsweringReads


async def test_stopping_observation_keeps_reads_but_sends_no_late_interest(workspace):
    workspace.thread("sender", title="Sender")
    workspace.thread("reader", title="Reader")
    message = workspace.comms.messaging.send("sender", "reader", "Read during view teardown").message
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        access = app.coordination_access
        observing = access.observation.observed()
        process = observing.process
        loop = asyncio.get_running_loop()
        acquired = asyncio.Event()
        request = ReadNotifications(str(workspace.roots.wire), (message.reference,))

        async def read_notifications():
            acquired.set()
            return await process.read(request)

        # Hold the readiness callback, not the service, so this acquired read
        # cannot resolve until stop_observing installs the read-only reader.
        loop.remove_reader(process.fileno())
        async with asyncio.TaskGroup() as reads:
            reading = reads.create_task(read_notifications())
            await acquired.wait()
            assert process.reads and not reading.done()
            await access.stop_observing()
            answering = access.observation
            assert type(answering) is AnsweringReads
            assert answering.process is process
            assert answering.service is observing.service
            assert answering.selection is observing.selection
            assert answering.sidebar is observing.sidebar
            assert answering.subscriptions is observing.subscriptions
            assert answering.updates is observing.updates

            requests = []

            def record_request(frame, event, result):
                if (event == "call" and frame.f_code is ObservationProcess.request.__code__
                        and frame.f_locals["self"] is process):
                    requests.append(frame.f_locals["request"])

            previous = sys.getprofile()
            sys.setprofile(record_request)
            try:
                answering.views_changed()
                answering.thread_interest(access)
                answering.observe_sidebar(access.sidebar_request())
                answering.observe_notifications(ObserveNotifications(frozenset()))
            finally:
                sys.setprofile(previous)
            assert requests == []
            result = await reading
            assert set(result) == {(message.seq, message.message_id)}
            assert process.process.is_alive()
