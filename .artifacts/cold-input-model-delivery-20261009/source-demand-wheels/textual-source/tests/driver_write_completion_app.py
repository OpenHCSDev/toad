"""One source Linux App confirms a real terminal writer acknowledgment."""

import asyncio
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import signal
from threading import Thread, get_ident
from time import sleep

from textual.app import App
from textual.drivers.linux_driver import LinuxDriver
from textual.drivers.web_driver import WebDriver
from textual.widgets import Static


class CompletionApp(App):
    def __init__(self):
        self.requested = False
        self.received = False
        self.owner_thread = get_ident()
        self.writer = None
        super().__init__(driver_class=LinuxDriver)

    def compose(self):
        yield Static("Native driver write completion")

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if renderable is not None and not self._batch_count and not self.requested:
            self.requested = True
            self.writer = self._driver._writer_thread
            self._driver.call_after_flush(self.written)

    def written(self):
        assert get_ident() == self.owner_thread
        assert asyncio.get_running_loop() is self._driver._loop
        assert self.writer.is_alive()
        self.received = True
        self.exit()


async def web_transport_completion():
    """Interrupt a real large pipe write after progress, then recover its tail."""
    loop = asyncio.get_running_loop()
    driver = WebDriver(App())
    read_fd, write_fd = os.pipe()
    driver.fileno = write_fd
    chunks = []

    def read_output():
        try:
            while data := os.read(read_fd, 4096):
                chunks.append(data)
                sleep(.0005)
        finally:
            os.close(read_fd)

    reader = Thread(target=read_output, name="native-web-output-reader")
    text = "frame-data-" * 100000
    payload = text.encode()
    expected = b"D" + len(payload).to_bytes(4, "big") + payload
    previous_handler = signal.getsignal(signal.SIGALRM)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    done = loop.create_future()
    profile = cProfile.Profile()
    reader.start()
    try:
        signal.signal(signal.SIGALRM, lambda *_: None)
        # This is a controlled kernel interruption in the verification program,
        # not a renderer timer or runtime workaround. Earlier bytes already fit
        # in the pipe, so os.write returns that partial progress on interruption.
        signal.setitimer(signal.ITIMER_REAL, .03)
        profile.enable()
        try:
            driver.write(text)
        finally:
            profile.disable()
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
        driver.call_after_flush(lambda: done.set_result((get_ident(), asyncio.get_running_loop())))
        assert not done.done()
        assert await asyncio.wait_for(done, 2) == (get_ident(), loop)
    finally:
        os.close(write_fd)
        reader.join(2)
        driver._input_reader.close()
        # No input thread was started for this output-only source control.
        driver._input_reader._selector.close()
    assert not reader.is_alive()
    received = b"".join(chunks)
    assert received == expected
    writes = sum(value[1] for (_, _, function), value in pstats.Stats(profile).stats.items()
                 if function == "<built-in method posix.write>")
    assert writes > 1
    return {"scope": "real WebDriver framed pipe write and App-loop callback, not browser pixels",
            "packet_bytes": len(received), "packet_sha256": hashlib.sha256(received).hexdigest(),
            "os_write_calls": writes, "owner_loop_completion": True,
            "reader_joined": True, "inputs": 0, "providers": 0}


async def main(output: Path, *, linux_only: bool = False):
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(XDG_CONFIG_HOME=str(output / "config"),
                      XDG_STATE_HOME=str(output / "state"),
                      XDG_DATA_HOME=str(output / "data"))
    if not linux_only:
        web = await web_transport_completion()
        (output / "web-output.json").write_text(json.dumps(web, indent=2) + "\n")
    app = CompletionApp()
    await asyncio.wait_for(app.run_async(mouse=False, size=(60, 10)), 15)
    assert app.received and app._exception is None
    assert app._driver._writer_thread is None
    assert not app.writer.is_alive()
    assert not app._driver._key_thread.is_alive()
    result = {"scope": "real source Linux App/PTY writer completion, not pixel presentation",
              "driver": type(app._driver).__name__, "callback_on_owner_loop": True,
              "writer_joined": True, "input_thread_joined": True,
              "inputs": 0, "providers": 0}
    (output / "linux-app.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    asyncio.run(main(Path(sys.argv[1]), linux_only="--linux-only" in sys.argv[2:]))
