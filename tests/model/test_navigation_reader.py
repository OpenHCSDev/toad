"""The navigation reader runs the latest request, drops superseded ones without I/O, and accounts for reads in flight at shutdown."""

import asyncio
import threading

from toad.navigation_preparation import NavigationReader, NavigationRequest


class GateRequest(NavigationRequest[str]):
    def __init__(self, name: str, *, fail: bool = False):
        self.name = name
        self.fail = fail
        self.entered = threading.Event()
        self.release = threading.Event()

    def read(self) -> str:
        self.entered.set()
        if not self.release.wait(8):
            raise TimeoutError("metadata gate was not released")
        if self.fail:
            raise ValueError("obsolete read failed")
        return self.name


async def test_superseded_requests_perform_no_io_and_shutdown_waits_for_a_real_read():
    reader = NavigationReader()
    requests = [GateRequest(str(index), fail=index == 1) for index in range(4)]
    tasks = []
    try:
        for request in requests[:2]:
            tasks.append(asyncio.create_task(reader.read(request)))
            assert await asyncio.to_thread(request.entered.wait, 2)
        tasks[0].cancel()
        await asyncio.gather(tasks[0], return_exceptions=True)
        for request in requests[2:]:
            tasks.append(asyncio.create_task(reader.read(request)))
            await asyncio.sleep(0)
        assert not requests[2].entered.is_set() and not requests[3].entered.is_set()
        requests[0].release.set()
        assert await asyncio.to_thread(requests[3].entered.wait, 2)
        assert not requests[2].entered.is_set(), "Superseded queue entry performed IO"
        requests[1].release.set()
        requests[3].release.set()
        assert await asyncio.gather(*tasks[1:]) == [None, None, "3"]
        closing_request = GateRequest("closing")
        requests.append(closing_request)
        tasks.append(asyncio.create_task(reader.read(closing_request)))
        assert await asyncio.to_thread(closing_request.entered.wait, 2)
        closing = asyncio.create_task(reader.aclose())
        await asyncio.sleep(0)
        assert not closing.done(), "Shutdown lost track of a real metadata read"
        closing_request.release.set()
        await closing
        assert await tasks[-1] is None
    finally:
        for request in requests:
            request.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await reader.aclose()
