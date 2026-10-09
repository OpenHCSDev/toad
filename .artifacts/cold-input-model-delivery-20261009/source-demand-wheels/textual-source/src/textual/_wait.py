from asyncio import sleep
from time import monotonic, thread_time

SLEEP_GRANULARITY: float = 1 / 50
SLEEP_IDLE: float = SLEEP_GRANULARITY / 20.0


async def wait_for_idle(
    min_sleep: float = SLEEP_GRANULARITY, max_sleep: float = 1
) -> None:
    """Wait until the calling event-loop thread isn't working very hard.

    Compare wall time with this thread's CPU time. Work on background threads
    cannot determine whether this event loop has drained its UI work.

    Thread idleness suggests input has been processed, but does not establish
    completion of a worker or domain operation; tests must await those receipts.

    Args:
        min_sleep: Minimum time to wait.
        max_sleep: Maximum time to wait.
    """
    start_time = monotonic()

    while True:
        cpu_time = thread_time()
        # Sleep for a predetermined amount of time
        await sleep(SLEEP_GRANULARITY)
        # Measure the owner whose idleness this test helper is waiting for.
        cpu_elapsed = thread_time() - cpu_time
        elapsed_time = monotonic() - start_time

        # If we have slept the maximum, we can break
        if elapsed_time >= max_sleep:
            break

        # If we have slept at least the minimum and the cpu elapsed is significantly less
        # than wall clock, then we can assume the process has finished working for now
        if elapsed_time > min_sleep and cpu_elapsed < SLEEP_IDLE:
            break
