"""An inotify burst schedules one shared notification per watched project."""

from pathlib import Path

from watchdog.events import FileCreatedEvent

from support.watchers import until
from toad.directory_watcher import _PathEventDispatcher


class Recipient:
    def __init__(self) -> None:
        self.events = []

    def on_any_event(self, event) -> None:
        self.events.append(event)


def dispatcher_with_recipients(count=14):
    dispatcher = _PathEventDispatcher(Path("/test/project"))
    recipients = [Recipient() for _ in range(count)]
    for recipient in recipients:
        dispatcher.add_watcher(recipient)
    return dispatcher, recipients


def test_a_burst_of_events_notifies_every_recipient_once():
    dispatcher, recipients = dispatcher_with_recipients()
    for index in range(500):
        dispatcher.on_any_event(FileCreatedEvent(f"/test/project/result-{index}"))
    assert all(not recipient.events for recipient in recipients)
    until(lambda: all(recipient.events for recipient in recipients), "the burst delivered")
    assert all(len(recipient.events) == 1 for recipient in recipients)


def test_a_change_after_a_flushed_burst_gets_its_own_notification():
    dispatcher, recipients = dispatcher_with_recipients()
    dispatcher.on_any_event(FileCreatedEvent("/test/project/first"))
    until(lambda: all(len(recipient.events) == 1 for recipient in recipients), "the first notification")
    # No final-state invalidation is lost when a source keeps changing after a flush.
    dispatcher.on_any_event(FileCreatedEvent("/test/project/final"))
    until(lambda: all(len(recipient.events) == 2 for recipient in recipients), "the second notification")


def test_removing_every_recipient_cancels_the_pending_notification():
    dispatcher, recipients = dispatcher_with_recipients()
    dispatcher.on_any_event(FileCreatedEvent("/test/project/removed"))
    pending = dispatcher._pending  # the timer that would deliver; joined so its outcome is settled
    for recipient in recipients:
        dispatcher.remove_watcher(recipient)
    pending.join()
    assert all(not recipient.events for recipient in recipients)
