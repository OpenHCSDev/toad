"""End-to-end fork test: drive the REAL toad binary in a pty.

No mocks: real toad-fork, real ACP server subprocess, real mouse clicks
(SGR sequences), real keyboard input. Row coordinates are parsed from
the rendered frames, so layout shifts don't break the test.
"""

import asyncio
import atexit
import json
import os
import signal
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Mapping

import pyte
from runtime_fixture import stop_test_owners

FORK_ROOT = Path(__file__).resolve().parents[1]
FORK_TOAD = FORK_ROOT / ".venv" / "bin" / "toad"
AGENT_PY = FORK_ROOT / ".venv" / "bin" / "python"
COMMS_CLI = FORK_ROOT / ".venv" / "bin" / "agent-comms"
TEST_ROOT = Path(os.environ.get("TOAD_E2E_ROOT", "/tmp"))
WIRE = TEST_ROOT / "toad-e2e-wire"
PROJECT = TEST_ROOT / "toad-e2e-proj"
PROGRESS_STUB = PROJECT / "pi-progress-stub"


def sgr_click(x: int, y: int, button: int = 0) -> bytes:
    return f"\x1b[<{button};{x};{y}M".encode() + f"\x1b[<{button};{x};{y}m".encode()


SCREEN_H = 40
SCREEN_W = 120


@dataclass(frozen=True)
class PtyLaunch:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]


class ToadSession:
    """Real toad on a fixed-size pty: the screen is always the last
    SCREEN_H lines of the output buffer."""

    def __init__(self, launch: PtyLaunch | None = None) -> None:
        self.launch = launch
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
        root = Path(self.launch.environment["AGENT_COMMS_ROOT"]) if self.launch else WIRE
        if root.exists():
            stop_test_owners(root)

    async def stop(self) -> None:
        """Reap the isolated UI and its servers before removing their temporary wire."""
        import psutil

        if self.proc is None or self.proc.returncode is not None:
            return
        children = psutil.Process(self.proc.pid).children(recursive=True)
        self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), 5)
        except TimeoutError:
            self.close()
            await self.proc.wait()
        _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=5)
        for child in alive:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        await asyncio.to_thread(psutil.wait_procs, alive, timeout=5)
        root = Path(self.launch.environment["AGENT_COMMS_ROOT"]) if self.launch else WIRE
        await asyncio.to_thread(stop_test_owners, root)

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
            AGENT_COMMS_AGENT_BIN=str(PROGRESS_STUB),
            AGENT_COMMS_AGENT_ARGS="--provider test --model cursor-ux",
            AGENT_COMMS_AGENT_MODELS="test/alternative,test/cursor-ux",
            XDG_CONFIG_HOME=str(PROJECT / ".config"),
            XDG_STATE_HOME=str(PROJECT / ".state"),
            TERM="xterm-256color",
        )
        command = self.launch.command if self.launch else (
            str(FORK_TOAD),
            "acp",
            f"{AGENT_PY} -m agent_comms.acp",
        )
        if self.launch:
            env.update(self.launch.environment)
        self.proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(self.launch.cwd if self.launch else PROJECT),
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

        self._drain()
        self.terminal.resize(lines=h, columns=w)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        # This harness uses start_new_session without claiming a controlling TTY,
        # so the kernel has no foreground process group to notify automatically.
        if self.proc is not None:
            os.kill(self.proc.pid, signal.SIGWINCH)

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

    async def next_output(self, timeout: float = 3) -> str:
        """Parse the next real PTY write without a timed polling interval."""
        assert self.master is not None
        readable = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_reader(self.master, readable.set)
        try:
            await asyncio.wait_for(readable.wait(), timeout)
        finally:
            loop.remove_reader(self.master)
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

    async def click_text(self, text: str, *, last: bool = False, button: int = 0) -> bool:
        """Click the first visible occurrence of text at its rendered position."""
        await asyncio.sleep(0.2)
        lines = list(enumerate(self.screen_lines()))
        for index, line in reversed(lines) if last else lines:
            column = line.find(text)
            if column >= 0:
                await self.click(column + 1, index + 1, button)
                return True
        return False

    @staticmethod
    def _is_row(stripped: str, name: str) -> bool:
        return (
            stripped == name
            or stripped.startswith(f"{name} ")
            or (
                stripped.startswith(("●", "✓", "?", "⌛"))
                and name in stripped
                and len(stripped) < 45
            )
            or (
                stripped.startswith(("○", "▶", "▸", "▾"))
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
    (PROJECT / "preview.md").write_text("# PTY file preview\n\nOpened as a native session tab.\n")
    PROGRESS_STUB.write_text(
        """#!/bin/sh
printf '%s\n' '{"type":"response","command":"get_state","success":true,"data":{"model":{"provider":"test","id":"cursor-ux","contextWindow":1000}}}'
IFS= read -r state
IFS= read -r prompt
printf '%s\n' "$prompt" | python3 -c 'import json,sys; request=json.load(sys.stdin); print(json.dumps({"type":"response","command":"prompt","id":request["id"],"success":True}),flush=True); print(json.dumps({"type":"message_start","message":{"role":"user","content":[{"type":"text","text":request["message"]}]}}),flush=True)'
printf '%s\n' '{"type":"message_update","assistantMessageEvent":{"type":"thinking_delta","delta":"Inspecting workspace"}}'
sleep 2
printf '%s\n' '{"type":"tool_execution_start","toolCallId":"t1","toolName":"bash","args":{"command":"pwd"}}'
printf '%s\n' '{"type":"tool_execution_update","toolCallId":"t1","toolName":"bash","partialResult":{"content":[{"type":"text","text":"checking files"}]}}'
sleep 2
"""
        + f'"{COMMS_CLI}" rename-self --to renamed-e2e >/dev/null\n'
        + """
printf '%s\n' '{"type":"tool_execution_end","toolCallId":"t1","toolName":"bash","result":{"content":[{"type":"text","text":"/tmp/toad-e2e-proj"}]},"isError":false}'
 printf '%s\n' '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Analysis complete. See preview.md"}}'
printf '%s\n' '{"type":"message_end","message":{"role":"assistant","stopReason":"stop"}}'
printf '%s\n' '{"type":"agent_settled"}'
printf '%s\n' '{"type":"response","command":"get_session_stats","success":true,"data":{"contextUsage":{"tokens":100,"contextWindow":1000}}}'
"""
    )
    PROGRESS_STUB.chmod(0o755)
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
    assert (
        "Channels" in frame and "#none" in frame and "seed-peer" in frame
    ), f"sidebar missing at launch:\n{frame[-600:]}"
    assert ("◀──" in frame.splitlines()[0] and "──▶" in frame.splitlines()[0]), (
        "Large tab Back/Forward controls are not above Channels"
    )
    print("[1] launch + sidebar render OK")

    for _ in range(20):
        frame = await session.frame(0.5)
        if "test/cursor-ux" in frame and "Initializing" not in frame:
            break
    else:
        raise AssertionError(f"agent did not become ready:\n{frame[-900:]}")

    await session.click(78, 36)
    await session.frame(0.2)
    await session.type_text("inspect the project")
    await asyncio.sleep(0.3)
    await session.press_enter()
    for _ in range(30):
        frame = await session.frame(0.1)
        if "Inspecting workspace" in frame:
            break
    else:
        raise AssertionError(f"thinking trace missing:\n{frame}")
    for _ in range(30):
        frame = await session.frame(0.1)
        if "Run pwd" in frame and "running" in frame:
            break
    else:
        raise AssertionError(f"running tool progress missing:\n{frame[-900:]}")
    for _ in range(30):
        frame = await session.frame(0.1)
        if "Analysis complete" in frame:
            break
    else:
        raise AssertionError(f"final response missing:\n{frame[-900:]}")
    async def toggle_right_sidebar():
        # The top navigation row changes the toggle's Y coordinate. Follow
        # its actual painted glyph instead of clicking a stale fixed cell.
        await session.frame(.1)
        lines = session.screen_lines()
        for y in range(SCREEN_H // 2 - 4, SCREEN_H // 2 + 5):
            for x in range(SCREEN_W - 8, SCREEN_W):
                if lines[y][x] in "<>":
                    await session.click(x + 1, y + 1)
                    return
        raise AssertionError("Right sidebar toggle is not visible near the right edge")

    # Thread identity lives in the independent right-hand details panel.
    await toggle_right_sidebar()
    for _ in range(20):
        frame = await session.frame(0.1)
        if "Thread: renamed-e2e" in frame and "inspect the project" in frame.lower():
            break
    else:
        raise AssertionError(f"wire rename did not reach Toad UI:\n{frame[-1200:]}")
    for _ in range(30):
        frame = await session.frame(.1)
        if "Comms" in frame and "In/out only" in frame and "Last inbound" in frame:
            break
    else:
        raise AssertionError(f"Default-expanded right Comms panel did not load:\n{frame}")
    assert await session.click_text("In/out only"), frame
    frame = await session.frame(.3)
    assert "Analysis complete" not in frame and "inspect the project" not in frame.lower(), frame
    assert await session.click_text("In/out only"), frame
    frame = await session.frame(.3)
    assert "Analysis complete" in frame, "Unchecking the filter lost the response"
    print("[right Comms] real header/owner/filter controls render; filter toggles and restores transcript")
    await toggle_right_sidebar()
    await session.frame(0.2)
    print("[2] real ACP thinking + tool progress + response OK")

    assert await session.click_text("preview.md", button=2), "File link not visible for menu"
    frame = await session.frame(.4)
    assert "Copy full path" in frame, "Right-click file link did not offer path copy"
    assert await session.click_text("Copy full path")
    frame = await session.frame(.3)
    assert "Analysis complete" in frame, "Copy action opened the file instead"
    assert await session.click_text("preview.md"), "File link not visible for navigation"
    frame = await session.frame(.8)
    assert "PTY file preview" in frame and "Opened as a native session tab" in frame
    assert "preview.md" in frame
    for row_index, line in enumerate(session.screen_lines()):
        if "preview.md" in line and "×" in line[line.index("preview.md"):]:
            await session.click(line.index("×", line.index("preview.md")) + 1, row_index + 1)
            break
    else:
        raise AssertionError(f"Native preview tab close button missing:\n{frame}")
    frame = await session.frame(.8)
    assert "Analysis complete" in frame, "Closing file preview did not restore agent tab"
    print("[file preview] real link menu copies path; native tab opens and closes back to conversation")

    # Open and operate the pointer-anchored context menu with real mouse/key input.
    assert await session.click_row(
        "seed-peer", button=2
    ), "seed-peer row not found:\n" + "\n".join(session.last_screen_lines)
    frame = await session.frame(1.0)
    assert (
        "Fork from this thread" in frame
    ), f"context menu did not open:\n{frame[-900:]}"
    assert session.alive(), "toad died opening the right-click menu"
    assert await session.click_text("Fork from this thread")
    frame = await session.frame(0.8)
    assert "Fork from @seed-peer" in frame, f"fork dialog did not open:\n{frame[-900:]}"
    assert session.alive(), "toad died opening the fork dialog"
    await session.key("\x1b")
    await session.frame(0.5)
    assert session.alive(), "toad died dismissing the fork dialog"
    print("[3] pointer context menu + fork dialog open and dismiss OK")

    # Click '#all': this must create a native tracked Toad session/mode.
    assert await session.click_row("#all"), "#all row not found:\n" + "\n".join(
        session.last_screen_lines
    )
    channel_click_at = time.perf_counter()
    if profile := os.environ.get("TOAD_NAV_PROFILE"):
        with Path(profile).open("a") as timeline:
            timeline.write(json.dumps({"time_ns": time.perf_counter_ns(),
                                       "pid": os.getpid(), "kind": "input_write_done"}) + "\n")
    # The real terminal must see the channel route before the expensive
    # composer/sidebar/history tree appears. Headless _display probes cannot
    # verify this: they may invoke after-refresh callbacks without writing a
    # terminal frame.
    shell_seen = False
    opening_trace = []
    async with asyncio.timeout(3):
        while not shell_seen:
            opening = await session.next_output()
            opening_trace.append((len(session.buffer), "Opening #all" in opening,
                                  "channel greeting from seed" in opening))
            if "Opening #all" in opening:
                shell_seen = True
            if "channel greeting from seed" in opening:
                break
    assert shell_seen, ("channel controls appeared before a painted route frame",
                        opening_trace[:10], opening_trace[-10:],
                        "Opening #all" in session.buffer.decode("utf-8", "replace"))
    print(f"[cold] terminal-observed channel route: {(time.perf_counter() - channel_click_at) * 1000:.1f} ms")
    frame = await session.frame(1.5)
    assert (
        "channel greeting from seed" in frame
    ), f"channel session did not open:\n{frame[-900:]}"
    assert "#all" in frame, f"native channel session tab missing:\n{frame[-900:]}"
    print("[4] channel click opens native session + history renders OK")
    if os.environ.get("TOAD_E2E_COLD_ONLY") == "1":
        await session.stop()
        return

    # The chat composer should be focused; type and send.
    await session.type_text("hello from the pty test")
    await session.press_enter()
    await asyncio.sleep(2)
    frame = await session.frame(0.2)
    history = [m.body for m in comms.channel_history("#all")]
    assert (
        "hello from the pty test" in history
    ), f"send failed; wire history: {history[-3:]}\n{frame[-900:]}"
    print("[5] composer send lands on wire OK")

    # Escape returns to the original agent mode without closing the channel tab.
    await session.key("\x1b")
    frame = await session.frame(1.2)
    assert (
        "❯" in frame or "New Session" in frame
    ), f"did not return to agent session:\n{frame[-900:]}"
    print("[6] escape restores agent session OK")

    # Reopening the same target reuses its native mode; Escape returns again.
    assert await session.click_row(
        "#all"
    ), "#all row not found on return:\n" + "\n".join(session.last_screen_lines)
    frame = await session.frame(1.0)
    assert "hello from the pty test" in frame, "reused channel lost its history"
    await session.key("\x1b")
    await session.frame(0.8)
    print("[7] native channel session is reused OK")

    # Ctrl+W edits the composer; the tab's close button controls its lifecycle.
    assert await session.click_row("seed-peer"), "seed-peer row not found for DM"
    frame = await session.frame(1.0)
    assert (
        "@seed-peer" in frame and "Message seed-peer" in frame
    ), f"DM session did not open:\n{frame[-900:]}"
    await session.type_text("keep delete")
    await session.key("\x17")  # ctrl+w deletes the previous word
    frame = await session.frame(0.5)
    assert "@seed-peer" in frame and "keep" in frame and "keep delete" not in frame
    for row_index, line in enumerate(session.screen_lines()):
        if "@seed-peer" in line and "×" in line[line.index("@seed-peer"):]:
            await session.click(line.index("×", line.index("@seed-peer")) + 1, row_index + 1)
            break
    else:
        raise AssertionError("DM close button not visible")
    await session.frame(1.0)
    assert session.alive(), "toad died closing the DM session"
    print("[8] DM native session opens and closes OK")

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
    print("[9] resize + repeated native IRC toggles: app alive")

    # Closing the final agent session should replace it with another session
    # for the same configured agent, not leak into Toad's generic Store.
    assert await session.click_row(
        "renamed e2e", button=2
    ), "human-named local session row not found:\n" + "\n".join(
        session.last_screen_lines
    )
    frame = await session.frame(0.5)
    assert "Stop process" in frame and "Close view" in frame
    assert await session.click_text("Close view")
    for _ in range(30):
        frame = await session.frame(0.2)
        active = comms.registry.active_threads()
        if (
            "Agent Store" not in frame
            and "toad-e2e-proj-2" in frame
            and "test/cursor-ux" in frame
            and "toad-e2e-proj-2" in active
        ):
            break
    else:
        output = session.buffer.decode("utf-8", "replace")[-4000:]
        raise AssertionError(
            f"closing final session failed (alive={session.alive()}):\n"
            f"frame:\n{frame[-1200:]}\noutput:\n{output}"
        )
    assert comms.registry.status("renamed-e2e").value == "running"
    assert comms._process_alive(comms.registry.require("renamed-e2e").pid)
    print("[10] final close replaces the view while its detached owner stays alive OK")

    assert await session.click_text("test/cursor-ux", last=True)
    frame = await session.frame(0.3)
    assert "test/alternative" in frame, f"model selector missing:\n{frame}"
    await session.type_text("alternative")
    await session.frame(0.3)
    await session.press_enter()
    for _ in range(20):
        frame = await session.frame(0.2)
        if comms.registry.require("toad-e2e-proj-2").model == "test/alternative":
            break
    else:
        raise AssertionError(f"model selection did not persist:\n{frame}")
    assert "test/alternative" in frame
    assert "Thinking level for" in frame, f"thinking selector missing:\n{frame}"
    assert await session.click_text("High")
    for _ in range(20):
        frame = await session.frame(0.2)
        if comms.registry.require("toad-e2e-proj-2").thinking_level == "high":
            break
    else:
        raise AssertionError(f"thinking selection did not persist:\n{frame}")
    print("[11] terminal model and thinking selectors persist both choices OK")

    # Bracketed paste enters a complete command without invoking completion.
    assert await session.click_text("❯", last=True)
    await session.send(b"\x1b[200~/goal Verify the terminal goal controls\x1b[201~")
    await session.press_enter()
    for _ in range(30):
        frame = await session.frame(0.2)
        if "Goal" in frame and "Pause" in frame:
            break
    else:
        raise AssertionError(f"goal row missing:\n{frame}")
    assert await session.click_text("Pause")
    for _ in range(20):
        frame = await session.frame(0.2)
        if "Resume" in frame:
            break
    assert comms.registry.require("toad-e2e-proj-2").goal.status == "paused"
    assert await session.click_text("Clear")
    await session.frame(0.5)
    assert comms.registry.require("toad-e2e-proj-2").goal is None
    print("[12] terminal /goal, Pause, Resume display and Clear controls OK")

    await session.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
