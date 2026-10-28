"""Textual-facing: widget unmount; unmount ends interest, not the real observer's already-acquired reads."""

import asyncio
import sys
import pytest

from agent_comms.notification_reads import LiveNotificationRead
from agent_comms.ui_model.observation import ObservationProcess, ObserverDied, ObserveNotifications, ReadNotifications
from toad.comms_root import AnsweringReads


async def test_an_observer_dying_during_shutdown_still_releases_its_resources(workspace):
    with pytest.raises(BaseExceptionGroup) as failures:
        async with workspace.app() as ui:
            access = ui.app.coordination_access
            await access.current_sidebar()
            observed = access.observation.observed()
            process = observed.process
            # The death has not been delivered to receive(); stop_updates must
            # encounter it at its actual StopObserving request during shutdown.
            asyncio.get_running_loop().remove_reader(process.fileno())
            process.process.kill()
            await asyncio.to_thread(process.process.join, 5)
            assert process.process.exitcode is not None
            assert not process.connection.closed
    assert failures.value.subgroup(ObserverDied) is not None
    assert process.connection.closed
    assert not process.process.is_alive()
    assert not access.retiring




async def test_stopping_observation_keeps_reads_but_sends_no_late_interest(workspace):
    workspace.thread("sender", title="Sender")
    workspace.thread("reader", title="Reader")
    message = workspace.comms.messaging.send("sender", "reader", "Read during view teardown").message
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        access = app.coordination_access
        previous_observer = access.observation.observed()
        observing = await access.preparation.run_thread(access.open_selected, previous_observer.selection)
        await ui.step()
        # Retiring the old process must not publish its state over the new one.
        assert access.observation is observing
        process = observing.process
        loop = asyncio.get_running_loop()
        acquired = asyncio.Event()
        request = ReadNotifications(str(workspace.roots.wire), LiveNotificationRead((message.reference,)))

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
                await access.stop_observing()
                assert access.observation is answering
            finally:
                sys.setprofile(previous)
            assert requests == []
            result = await reading
            assert set(result) == {(message.seq, message.message_id)}
            assert process.process.is_alive()
