import asyncio
import gc
from weakref import ref

import pytest

from textual.app import App
from textual.timer import Timer


class Target:
    def post_message(self, _message):
        return True

    def callback(self):
        pass


@pytest.mark.parametrize("bulk", [False, True])
async def test_stopped_timer_does_not_retain_its_callback_owner(bulk):
    target = Target()
    weak_target = ref(target)
    timer = Timer(target, 30, callback=target.callback, pause=True)
    timer._start()
    await asyncio.sleep(0)
    if bulk:
        await Timer._stop_all((timer,))
    else:
        timer.stop()
        await asyncio.sleep(0)
    del target
    gc.collect()
    assert weak_target() is None, "Stopped timer retained its callback owner"


async def test_completed_one_shot_releases_callback_and_task_context():
    app = App()
    async with app.run_test():
        target = Target()
        weak_target = ref(target)
        timer = Timer(target, .001, callback=target.callback, repeat=0)
        timer._start()
        task = timer._task
        await task
        del target, task
        gc.collect()
        assert weak_target() is None, "Completed one-shot retained callback ownership"
        assert timer._task is None


async def test_pause_and_resume_retain_the_live_callback():
    app = App()
    async with app.run_test():
        called = asyncio.Event()
        target = Target()
        timer = Timer(target, .001, callback=called.set, pause=True, repeat=0)
        timer._start()
        await asyncio.sleep(.01)
        assert not called.is_set()
        timer.resume()
        await asyncio.wait_for(called.wait(), 1)
        await Timer._stop_all((timer,))
