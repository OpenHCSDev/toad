"""Local, user-visible POSIX PTY for package-owned MCP decisions.

No challenge is read, computed, queued, or answered by Toad. The Pi package
owns the complete declaration display, challenge, validation and ledger write.
"""

from __future__ import annotations

import asyncio
import codecs
import errno
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Awaitable, Callable

from toad.mcp_inventory import installed_mcp_command, read_inventory
from toad.terminal_execution import PtyProcess
from toad.ansi import TerminalState
from toad.mcp_commands import MCPDecision, MCPSelection
from toad.mcp_outcomes import (
    DecisionOutcome, ControllerLostOutcome, ExitedZeroOutcome, ExitedErrorOutcome,
    OutputLimitOutcome, StaleSnapshotOutcome, TimeoutOutcome, UnavailableOutcome,
    UnknownOutcome, UnsupportedOutcome,
)


DECISION_TIMEOUT_SECONDS = 120.0
MAX_DECISION_OUTPUT_BYTES = 128_000


class LocalDecisionPTY:
    """One local action, cancelled with its visible controller."""

    def __init__(self, controller_visible: Callable[[], bool]) -> None:
        self._controller_visible = controller_visible
        self._custody: asyncio.Future[PtyProcess] = asyncio.get_running_loop().create_future()

    async def write_user_input(self, text: str) -> None:
        """Only Textual's focused terminal key/paste events may call this."""
        if (not self._controller_visible() or not self._custody.done()
                or self._custody.cancelled() or len(text) > 8_192):
            return
        await self._custody.result().write(text.encode("utf-8"))

    async def custody(self) -> PtyProcess:
        """Borrow the original acquisition, including its retired handles."""
        return await asyncio.shield(self._custody)

    async def run(
        self,
        *,
        selection: MCPSelection,
        command: MCPDecision,
        show: Callable[[str], Awaitable[None]],
        state: TerminalState,
    ) -> DecisionOutcome:
        """Recheck the typed package snapshot before a direct exec, then show raw PTY output.

        The return is a *process outcome*, never an approval receipt. On failure,
        no child is started; after spawn all output is human-visible or the child
        is killed at the output cap. The caller must not infer a ledger decision.
        """
        try:
            if os.name != "posix" or not self._controller_visible():
                return UnavailableOutcome()
            if not command.available(selection):
                return UnsupportedOutcome()
            try:
                node, cli = await asyncio.to_thread(installed_mcp_command)
            except (OSError, ValueError, RuntimeError):
                return UnavailableOutcome()
            fresh = await read_inventory(selection.inventory.root)
            if not self._controller_visible() or not selection.matches(fresh):
                return StaleSnapshotOutcome()

            env = os.environ.copy()
            env.pop("NODE_OPTIONS", None)
            env.pop("NODE_PATH", None)
            try:
                async with AsyncExitStack() as custody:
                    acquired = await PtyProcess.acquire(
                        (str(node), str(cli), *command.apply(selection)),
                        env=env, cwd=str(Path(cli).parent), width=state.width, height=state.height,
                        custody=custody,
                    )
                    self._custody.set_result(acquired)
                    if not self._controller_visible():
                        return ControllerLostOutcome()
                    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                    read_bytes = 0

                    async def relay() -> DecisionOutcome:
                        nonlocal read_bytes
                        while self._controller_visible():
                            try:
                                data = await acquired.reader.read(4096)
                            except OSError as error:
                                if error.errno != errno.EIO:
                                    raise
                                data = b""  # POSIX EOF on the original master.
                            if not data:
                                break
                            read_bytes += len(data)
                            if read_bytes > MAX_DECISION_OUTPUT_BYTES:
                                acquired.kill()
                                return OutputLimitOutcome()
                            if rendered := decoder.decode(data):
                                await show(rendered)
                        if not self._controller_visible():
                            return ControllerLostOutcome()
                        await show(decoder.decode(b"", final=True))
                        original = await asyncio.wait_for(acquired.child.wait(), 2.0)
                        return ExitedZeroOutcome() if original.successful else ExitedErrorOutcome()

                    try:
                        return await asyncio.wait_for(relay(), DECISION_TIMEOUT_SECONDS)
                    except TimeoutError:
                        return TimeoutOutcome()
            except OSError, TimeoutError:
                return (UnknownOutcome() if self._custody.done() and not self._custody.cancelled()
                        else UnavailableOutcome())
        finally:
            if not self._custody.done():
                self._custody.cancel()

    def stop(self) -> None:
        """Revoke this SAME identity-bound child; its original scope reaps it."""
        if self._custody.done() and not self._custody.cancelled():
            self._custody.result().kill()
