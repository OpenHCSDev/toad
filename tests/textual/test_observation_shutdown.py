"""Textual-facing: widget unmount; unmount ends interest, not the real observer's already-acquired reads."""

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager

import pytest

from agent_comms.notification_reads import LiveNotificationRead
from agent_comms.ui_model.observation import (
    ObservationProcess, ObserverDied, ObserveNotifications, ReadNotifications, StopObserving,
    StopSidebar,
)
from toad.comms_root import AnsweringReads


async def stopped(pid: int) -> None:
    """Wait, bounded, until the stop is reported; WUNTRACED reports it without reaping."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        found, status = os.waitpid(pid, os.WNOHANG | os.WUNTRACED)
        if found:
            assert os.WIFSTOPPED(status) and os.WSTOPSIG(status) == signal.SIGSTOP
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"observer child {pid} did not stop")


@asynccontextmanager
async def held(process: ObservationProcess):
    """Hold this test's own observer child; resume it on every path while it lives."""
    pid = process.process.pid
    os.kill(pid, signal.SIGSTOP)
    try:
        await stopped(pid)
        yield pid
    finally:
        if process.process.is_alive():
            os.kill(pid, signal.SIGCONT)


async def settled(task: asyncio.Task) -> None:
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def empty_read(workspace) -> ReadNotifications:
    return ReadNotifications(str(workspace.roots.wire), LiveNotificationRead(()))


async def test_an_observer_dying_during_shutdown_still_releases_its_resources(workspace):
    died = None
    try:
        async with workspace.app() as ui:
            access = ui.app.coordination_access
            await access.current_sidebar()
            process = access.observation.observed().process
            assert not (await asyncio.wait_for(process.read(empty_read(workspace)), 30)).outcomes
            reading = None
            try:
                async with held(process) as pid:
                    reading = asyncio.create_task(process.read(empty_read(workspace)))
                    await asyncio.sleep(0)
                    assert process.reads and not reading.done()
                    os.kill(pid, signal.SIGKILL)
                with pytest.raises(ObserverDied) as death:
                    await asyncio.wait_for(reading, 10)
            finally:
                if reading is not None:
                    await settled(reading)
            died = death.value
            assert died.pid == pid
            assert died.exit_status == -signal.SIGKILL
            for request in (StopSidebar(), StopObserving()):
                with pytest.raises(ObserverDied) as again:
                    process.request(request)
                assert again.value is died
    except* ObserverDied as failures:
        assert died is not None
        _same, other = failures.split(lambda error: error is died)
        assert other is None
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
        assert not (await asyncio.wait_for(process.read(empty_read(workspace)), 30)).outcomes
        request = ReadNotifications(str(workspace.roots.wire), LiveNotificationRead((message.reference,)))
        reading = None
        try:
            # The observer child itself holds the answer; the UI's one receiver keeps running.
            async with held(process):
                reading = asyncio.create_task(process.read(request))
                await asyncio.sleep(0)
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
                assert not reading.done()
            result = await asyncio.wait_for(reading, 30)
        finally:
            if reading is not None:
                await settled(reading)
        assert set(result.outcomes) == {(message.seq, message.message_id)}
        assert process.process.is_alive()
