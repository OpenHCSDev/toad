"""A controlled clipboard subprocess pipe; production still uses its real reader."""
import asyncio


class ClipboardProcess:
    def __init__(self, data: bytes | None = None):
        self.stdout = asyncio.StreamReader()
        self.returncode: int | None = None
        self.killed = False
        if data is not None:
            self.emit(data)

    def emit(self, data: bytes) -> None:
        self.stdout.feed_data(data)
        self.stdout.feed_eof()

    async def wait(self) -> int:
        self.returncode = -9 if self.killed else 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.stdout.feed_eof()
