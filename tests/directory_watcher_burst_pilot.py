"""An inotify burst schedules one shared notification per watched project."""

import asyncio
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent

from toad.directory_watcher import _PathEventDispatcher


class Recipient:
    def __init__(self) -> None:
        self.events = []

    def on_any_event(self, event) -> None:
        self.events.append(event)


async def main():
    dispatcher = _PathEventDispatcher(Path("/test/project"))
    recipients = [Recipient() for _ in range(14)]
    for recipient in recipients:
        dispatcher.add_watcher(recipient)
    started = time.perf_counter()
    for index in range(500):
        dispatcher.on_any_event(FileCreatedEvent(f"/test/project/result-{index}"))
    scheduling_ms = (time.perf_counter() - started) * 1000
    assert all(not recipient.events for recipient in recipients)
    await asyncio.sleep(dispatcher.QUIET_INTERVAL + .06)
    assert all(len(recipient.events) == 1 for recipient in recipients)
    # A later change gets a new notification, so no final-state invalidation
    # is lost when a source keeps changing after the first burst was flushed.
    dispatcher.on_any_event(FileCreatedEvent("/test/project/final"))
    await asyncio.sleep(dispatcher.QUIET_INTERVAL + .06)
    assert all(len(recipient.events) == 2 for recipient in recipients)
    dispatcher.on_any_event(FileCreatedEvent("/test/project/removed"))
    for recipient in recipients:
        dispatcher.remove_watcher(recipient)
    await asyncio.sleep(dispatcher.QUIET_INTERVAL + .06)
    assert all(len(recipient.events) == 2 for recipient in recipients)
    print({"watchers": len(recipients), "events_in_burst": 500,
           "notifications": sum(len(recipient.events) for recipient in recipients),
           "schedule_500_events_ms": round(scheduling_ms, 2)})


if __name__ == "__main__":
    asyncio.run(main())
