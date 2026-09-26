"""Local, user-visible POSIX PTY for package-owned MCP decisions.

No challenge is read, computed, queued, or answered by Toad. The Pi package
owns the complete declaration display, challenge, validation and ledger write.
"""

from __future__ import annotations

import asyncio
import codecs
import errno
import hashlib
import os
import re
import secrets
from pathlib import Path
from typing import Awaitable, Callable, Literal

from toad.mcp_inventory import Declaration, Inventory, read_inventory


DecisionAction = Literal["trust", "calls"]
Decision = Literal["approve", "deny", "allow", "ask"]
# Positive grants need the independently cleared grant-revival fix. The CLI
# exposes no version/capability flag, so the user pins the SHA-256 of a
# verified installed script; Toad never owns or writes the package ledger.
POSITIVE_ACTIONS = {("trust", "approve"), ("calls", "allow")}


def cli_digest_matches(cli_path: str, expected_digest: str) -> bool:
    """A pinned digest is the only accepted supported-installation gate."""
    if not expected_digest or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        return False
    try:
        actual = hashlib.sha256(Path(cli_path).read_bytes()).hexdigest()
    except OSError:
        return False
    return secrets.compare_digest(actual, expected_digest)


DECISION_TIMEOUT_SECONDS = 120.0
MAX_DECISION_OUTPUT_BYTES = 128_000


class LocalDecisionPTY:
    """One local action, cancelled with its visible controller."""

    def __init__(self) -> None:
        self._master: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._active = False

    async def write_user_input(self, text: str) -> None:
        """Only Textual's focused terminal key/paste events may call this."""
        if not self._active or self._master is None or len(text) > 8_192:
            return
        try:
            os.write(self._master, text.encode("utf-8"))  # Nonblocking PTY.
        except OSError:
            pass  # A user may race an exited child or a full PTY buffer.

    async def run(
        self,
        *,
        inventory: Inventory,
        row: Declaration,
        action: DecisionAction,
        decision: Decision,
        node_path: str,
        cli_path: str,
        show: Callable[[str], Awaitable[None]],
        controller_visible: Callable[[], bool],
        cli_digest: str = "",
    ) -> str:
        """Recheck the typed package snapshot before a direct exec, then show raw PTY output.

        The return is a *process outcome*, never an approval receipt. On failure,
        no child is started; after spawn all output is human-visible or the child
        is killed at the output cap. The caller must not infer a ledger decision.
        """
        if os.name != "posix" or not controller_visible():
            return "unavailable"
        if (action, decision) not in {
            ("trust", "approve"),
            ("trust", "deny"),
            ("calls", "allow"),
            ("calls", "ask"),
        }:
            return "unsupported"
        if (action, decision) in POSITIVE_ACTIONS and not cli_digest_matches(
            cli_path, cli_digest
        ):
            # An older package build can revive a grant the running ledger fix
            # retired. Positive grants refuse every unpinned or changed CLI;
            # revocations stay available because they only narrow authority.
            return "unsupported_install"
        if (
            not row.effective
            or not row.enabled
            or not inventory.project_trusted_saved
            or (action == "trust" and row.scope != "project")
            or (action == "calls" and row.status != "approved")
        ):
            return "unsupported"
        # Explicit configuration, never a PATH lookup or a source checkout fallback.
        node, cli = Path(node_path), Path(cli_path)
        if (
            not node_path
            or not cli_path
            or not node.is_absolute()
            or not cli.is_absolute()
            or not node.is_file()
            or not cli.is_file()
        ):
            return "unavailable"
        fresh = await read_inventory(
            inventory.project_root, node_path=node_path, cli_path=cli_path
        )
        if (
            not controller_visible()
            or fresh is None
            or fresh != inventory
            or row not in (fresh.project if row.scope == "project" else fresh.user)
        ):
            return "stale_snapshot"

        import pty

        master, slave = pty.openpty()
        os.set_blocking(master, False)
        self._master = master
        process: asyncio.subprocess.Process | None = None
        try:
            env = os.environ.copy()
            env.pop("NODE_OPTIONS", None)
            env.pop("NODE_PATH", None)
            process = await asyncio.create_subprocess_exec(
                str(node),
                str(cli),
                action,
                decision,
                "--id",
                row.id,
                "--digest",
                row.digest,
                "--project",
                str(inventory.project_root),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(cli.parent),
                env=env,
                start_new_session=True,
            )
            self._process = process
            os.close(slave)
            slave = -1
            if not controller_visible():
                return "controller_lost"  # Hidden during spawn: never expose an input path.
            self._active = True
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            read_bytes = 0

            async def read_pty() -> bytes:
                loop = asyncio.get_running_loop()
                ready: asyncio.Future[bytes] = loop.create_future()

                def on_readable() -> None:
                    if ready.done():
                        return
                    try:
                        data = os.read(master, 4096)
                    except BlockingIOError:
                        return
                    except OSError as error:
                        if error.errno == errno.EIO:  # POSIX EOF on the master.
                            data = b""
                        else:
                            loop.remove_reader(master)
                            ready.set_exception(error)
                            return
                    loop.remove_reader(master)
                    ready.set_result(data)

                loop.add_reader(master, on_readable)
                try:
                    return await ready
                finally:
                    loop.remove_reader(master)

            async def relay() -> str:
                nonlocal read_bytes
                while controller_visible():
                    data = await read_pty()
                    if not data:
                        break
                    read_bytes += len(data)
                    if read_bytes > MAX_DECISION_OUTPUT_BYTES:
                        process.kill()
                        return "output_limit"
                    rendered = decoder.decode(data)
                    if rendered:
                        await show(rendered)
                if not controller_visible():
                    return "controller_lost"
                await show(decoder.decode(b"", final=True))
                return "exited"

            try:
                outcome = await asyncio.wait_for(relay(), DECISION_TIMEOUT_SECONDS)
            except TimeoutError:
                return "timeout"
            if outcome != "exited":
                return outcome
            code = await asyncio.wait_for(process.wait(), 2.0)
            return "exited_zero" if code == 0 else "exited_error"
        except OSError, TimeoutError:
            return "outcome_unknown" if process is not None else "unavailable"
        finally:
            self._active = False
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            if slave >= 0:
                os.close(slave)
            os.close(master)
            self._master = None
            self._process = None

    def stop(self) -> None:
        """Stop immediately when the visible controller is dismissed or hidden."""
        self._active = False
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.kill()
            except ProcessLookupError:
                pass
