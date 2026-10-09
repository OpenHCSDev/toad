"""Terminal-write callbacks acknowledge the write and flush, in order."""

import asyncio
from io import StringIO
from threading import get_ident

from textual.drivers._writer_thread import WriterThread


class RecordingOutput(StringIO):
    def __init__(self):
        super().__init__()
        self.events = []

    def write(self, text):
        self.events.append(("write", text))
        return super().write(text)

    def flush(self):
        self.events.append(("flush", self.getvalue()))
        return super().flush()


async def test_callback_follows_all_earlier_writes_and_flush():
    output = RecordingOutput()
    writer = WriterThread(output)
    done = asyncio.Event()
    callback_threads = []
    loop = asyncio.get_running_loop()

    def written():
        output.events.append(("callback", output.getvalue()))
        callback_threads.append(get_ident())
        done.set()

    writer.start()
    try:
        writer.write("opening")
        writer.write(" frame")
        writer.call_after_flush(written, loop)
        await asyncio.wait_for(done.wait(), 2)
        assert output.events.index(("flush", "opening frame")) < output.events.index(("callback", "opening frame"))
        assert callback_threads == [get_ident()]
        assert writer.ident != callback_threads[0]
    finally:
        writer.stop()
