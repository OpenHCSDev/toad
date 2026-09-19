"""End-to-end fork test: drive the REAL toad binary in a pty.

No mocks: real toad-fork, real ACP server subprocess, real mouse clicks
(SGR sequences), real keyboard input. Row coordinates are parsed from
the rendered frames, so layout shifts don't break the test.
"""

import asyncio
import atexit
import os
import signal
import sys
import time
from pathlib import Path

import pyte

FORK_ROOT = Path(__file__).resolve().parents[1]
FORK_TOAD = FORK_ROOT / ".venv" / "bin" / "toad"
AGENT_PY = FORK_ROOT / ".venv" / "bin" / "python"
WIRE = Path("/tmp/toad-e2e-wire")
PROJECT = Path("/tmp/toad-e2e-proj")


def sgr_click(x: int, y: int, button: int = 0) -> bytes:
    return f"\x1b[<{button};{x};{y}M".encode() + f"\x1b[<{button};{x};{y}m".encode()


SCREEN_H = 40
SCREEN_W = 120


class ToadSession:
    """Real toad on a fixed-size pty: the screen is always the last
    SCREEN_H lines of the output buffer."""

    def __init__(self) -> None:
        self.proc = None
        self.master = None
        self.buffer = b""
        self.last_screen_lines: list[str] = []
        self.terminal = pyte.Screen(SCREEN_W, SCREEN_H)
        self.stream = pyte.Stream(self.terminal)
        atexit.register(self.close)

    def close(self) -> None:
        if self.alive() and self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def start(self) -> None:
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        winsize = struct.pack("HHHH", SCREEN_H, SCREEN_W, 0, 0)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
        self.master = master
        env = dict(
            os.environ,
            AGENT_COMMS_ROOT=str(WIRE),
            TERM="xterm-256color",
        )
        self.proc = await asyncio.create_subprocess_exec(
            str(FORK_TOAD),
            "acp",
            f"{AGENT_PY} -m agent_comms.acp",
            cwd=str(PROJECT),
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        os.set_blocking(master, False)
        await asyncio.sleep(6)

    def _screen(self) -> str:
        self._drain()
        return "\n".join(self.terminal.display)

    def _set_size(self, h: int, w: int) -> None:
        import fcntl
        import struct
        import termios

        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        self.terminal.resize(lines=h, columns=w)

    def _drain(self) -> None:
        import select

        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            ready, _, _ = select.select([self.master], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(self.master, 262144)
            except BlockingIOError, OSError:
                break
            if not chunk:
                break
            self.buffer += chunk
            self.stream.feed(chunk.decode("utf-8", "replace"))

    def screen_lines(self) -> list[str]:
        return self._screen().splitlines()

    async def send(self, data: bytes) -> None:
        assert self.master is not None
        os.write(self.master, data)

    async def read_available(self, seconds: float = 1.5) -> str:
        await asyncio.sleep(seconds)
        return self._screen()

    async def frame(self, seconds: float = 1.5) -> str:
        await asyncio.sleep(seconds)
        return self._screen()

    async def click(self, x: int, y: int, button: int = 0) -> None:
        await self.send(sgr_click(x, y, button))

    async def click_row(self, name: str, button: int = 0, occurrence: int = 0) -> bool:
        """Parse the CURRENT screen (fixed-size pty), find the row, click."""
        await asyncio.sleep(0.4)
        lines = self.screen_lines()
        self.last_screen_lines = lines
        matches = [
            index
            for index, line in enumerate(lines)
            if self._is_row(line.split("▎", 1)[0].strip(), name)
        ]
        if len(matches) <= occurrence:
            return False
        index = matches[occurrence]
        await self.click(6, index + 1, button)
        return True

    @staticmethod
    def _is_row(stripped: str, name: str) -> bool:
        return (
            stripped == name
            or stripped.startswith(f"{name} ")
            or (stripped.startswith("●") and name in stripped and len(stripped) < 45)
            or (
                stripped.startswith(("○", "▶"))
                and name in stripped
                and len(stripped) < 45
            )
        )

    async def type_text(self, text: str) -> None:
        await self.send(text.encode())

    async def press_enter(self) -> None:
        await self.send(b"\r")

    async def key(self, k: str) -> None:
        await self.send(k.encode())

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


async def main() -> None:
    os.environ.pop("TOAD_COMMS_TEST_TARGET", None)
    os.makedirs(PROJECT, exist_ok=True)
    for stale in (
        "registry.json",
        "bus.jsonl",
        "read_markers.json",
        "activity.jsonl",
        "runtime_info.json",
    ):
        try:
            (WIRE / stale).unlink()
        except OSError:
            pass
    WIRE.mkdir(exist_ok=True)

    from agent_comms import Thread
    from agent_comms.operations import wire

    comms = wire(WIRE)
    comms.register(
        Thread(name="seed-peer", tags=frozenset({"seed"}), worktree=str(PROJECT))
    )
    comms.send("seed-peer", "#all", "channel greeting from seed")

    session = ToadSession()
    await session.start()
    assert session.alive(), "toad died on launch"
    frame = await session.frame(2.5)
    assert "CHANNELS" in frame and "WHO'S HERE" in frame and "seed-peer" in frame, (
        f"sidebar missing at launch:\n{frame[-600:]}"
    )
    print("[1] launch + sidebar render OK")

    # Open and operate the pointer-anchored context menu with real mouse/key input.
    assert await session.click_row("seed-peer", button=2), (
        "seed-peer row not found:\n" + "\n".join(session.last_screen_lines)
    )
    frame = await session.frame(1.0)
    assert "Fork from this thread" in frame, (
        f"context menu did not open:\n{frame[-900:]}"
    )
    assert session.alive(), "toad died opening the right-click menu"
    await session.press_enter()
    frame = await session.frame(0.8)
    assert "Fork from @seed-peer" in frame, f"fork dialog did not open:\n{frame[-900:]}"
    assert session.alive(), "toad died opening the fork dialog"
    await session.key("\x1b")
    await session.frame(0.5)
    assert session.alive(), "toad died dismissing the fork dialog"
    print("[2] pointer context menu + fork dialog open and dismiss OK")

    # Click '#all': this must create a native tracked Toad session/mode.
    assert await session.click_row("#all"), "#all row not found:\n" + "\n".join(
        session.last_screen_lines
    )
    frame = await session.frame(1.5)
    assert "channel greeting from seed" in frame, (
        f"channel session did not open:\n{frame[-900:]}"
    )
    assert "#all" in frame, f"native channel session tab missing:\n{frame[-900:]}"
    print("[3] channel click opens native session + history renders OK")

    # The chat composer should be focused; type and send.
    await session.type_text("hello from the pty test")
    await asyncio.sleep(0.3)
    await session.press_enter()
    await asyncio.sleep(2)
    frame = await session.frame(0.2)
    history = [m.body for m in comms.channel_history("#all")]
    assert "hello from the pty test" in history, (
        f"send failed; wire history: {history[-3:]}\n{frame[-900:]}"
    )
    print("[4] composer send lands on wire OK")

    # Escape returns to the original agent mode without closing the channel tab.
    await session.key("\x1b")
    frame = await session.frame(1.2)
    assert "How can I help you today?" in frame or "New Session" in frame, (
        f"did not return to agent session:\n{frame[-900:]}"
    )
    print("[5] escape restores agent session OK")

    # Reopening the same target reuses its native mode; Escape returns again.
    assert await session.click_row("#all"), (
        "#all row not found on return:\n" + "\n".join(session.last_screen_lines)
    )
    frame = await session.frame(1.0)
    assert "hello from the pty test" in frame, "reused channel lost its history"
    await session.key("\x1b")
    await session.frame(0.8)
    print("[6] native channel session is reused OK")

    # Open a DM as another native mode, then close it with the priority binding.
    assert await session.click_row("seed-peer"), "seed-peer row not found for DM"
    frame = await session.frame(1.0)
    assert "@seed-peer" in frame and "Message seed-peer" in frame, (
        f"DM session did not open:\n{frame[-900:]}"
    )
    await session.key("\x17")  # ctrl+w
    await session.frame(1.0)
    assert session.alive(), "toad died closing the DM session"
    print("[7] DM native session opens and closes OK")

    # Resize and repeatedly toggle the reusable IRC mode from the agent mode.
    await session.key("\x1b")
    await session.frame(0.8)
    session._set_size(34, 96)
    await asyncio.sleep(0.5)
    session._set_size(SCREEN_H, SCREEN_W)
    for index in range(3):
        await session.key("\x07")  # ctrl+g: open IRC
        await session.frame(0.5)
        assert session.alive(), f"toad died opening IRC on soak iteration {index}"
        await session.key("\x07")  # ctrl+g: back to agent
        await session.frame(0.5)
        assert session.alive(), f"toad died leaving IRC on soak iteration {index}"
    print("[8] resize + repeated native IRC toggles: app alive")

    session.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
