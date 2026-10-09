"""Original driver output boundaries publish on the original App loop."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile
from threading import get_ident

import pytest

from textual.app import App
from textual.drivers._writer_thread import WriterThread


async def test_headless_completion_is_scheduled_on_its_original_loop():
    app = App()
    async with app.run_test() as pilot:
        await pilot.pause()
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        thread = get_ident()
        app._driver.call_after_flush(lambda: done.set_result((get_ident(), asyncio.get_running_loop())))
        assert not done.done()
        assert await asyncio.wait_for(done, 2) == (thread, loop)


@pytest.mark.skipif(sys.platform == "win32", reason="Original inline driver is POSIX-only")
async def test_inline_file_is_flushed_before_owner_loop_completion():
    from textual.drivers.linux_inline_driver import LinuxInlineDriver

    app = App()
    async with app.run_test() as pilot:
        await pilot.pause()
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        driver = LinuxInlineDriver(app)
        with tempfile.TemporaryFile(mode="w+") as output:
            # Original synchronous output owner, using a real buffered file.
            driver._file = output
            driver.write("inline output")
            driver.call_after_flush(lambda: done.set_result((
                os.pread(output.fileno(), 13, 0), get_ident(), asyncio.get_running_loop())))
            assert not done.done()
            assert await asyncio.wait_for(done, 2) == (b"inline output", get_ident(), loop)
        driver.close()


async def test_writer_drains_signals_before_close_and_drops_retired_loop(tmp_path: Path):
    loop = asyncio.get_running_loop()
    retired = asyncio.new_event_loop()
    retired.close()
    observed = []
    done = loop.create_future()
    with (tmp_path / "output.txt").open("w") as output:
        writer = WriterThread(output)
        writer.start()
        try:
            writer.write("first")
            writer.call_after_flush(lambda: observed.append("retired"), retired)
            writer.write(" second")
            writer.call_after_flush(lambda: done.set_result((tmp_path / "output.txt").read_text()), loop)
            # Joining output does not wait for the App loop callback, which is
            # scheduled by the original writer and remains owned by that loop.
            writer.stop()
            assert not writer.is_alive()
            assert await asyncio.wait_for(done, 2) == "first second"
            assert observed == []
        finally:
            if writer.is_alive():
                writer.stop()
