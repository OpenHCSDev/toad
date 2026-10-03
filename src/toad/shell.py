from __future__ import annotations

import asyncio
import codecs
import os
from contextlib import AsyncExitStack
import logging
from agent_comms.child_process import ControllingTerminalCommand
from toad.surface_binding import SurfaceBinding
from toad.core.source_events import CurrentWorkingDirectoryChanged

from toad.shell_read import shell_read
from toad.terminal_environment import TerminalEnvironment
from toad import ansi
from toad.shell_output import ShellCommandOutput, ShellTerminalOutput
from toad.shell_source import ShellOperationalSource
from toad.terminal_execution import Command, PtyProcess, TerminalCompletion


class Shell(ShellOperationalSource):
    """Own one retained shell process and its original terminal output."""

    def __init__(
        self,
        working_directory: str,
        *,
        terminal_size: tuple[int, int],
        shell="",
        start="",
        hide_start: bool = True,
    ) -> None:
        super().__init__(terminal_size)
        self.working_directory = working_directory

        self.new_log: bool = False
        self.shell = shell
        self.shell_start = start
        self.hide_start = hide_start

        self._hide_echo: set[bytes] = set()
        """A set of byte strings to remove from output."""

        self._hide_output = hide_start
        self._pending_directory: str | None = None
        """Hide all output."""

    @property
    def pending_directory(self) -> str | None:
        return self._pending_directory

    async def is_busy(self) -> bool:
        """Observe the children of this SAME acquired shell incarnation."""
        custody = await self._operation.custody()
        import psutil

        def children():
            if not custody.child.alive():
                return False
            try:
                return bool(psutil.Process(custody.child.pid).children(recursive=True))
            except psutil.NoSuchProcess, psutil.AccessDenied:
                return False

        return await asyncio.to_thread(children)

    async def send(self, command: str, width: int, height: int) -> None:
        await self.wait_for_ready()
        self._terminal_size = width, height

        if self.output is not None:
            self.output.finalize()
            self.output = None
        command_output = ShellCommandOutput(command)
        self.outputs.append(command_output)
        await self._present(command_output)

        self._operation.resize(width, max(height, 1))

        if self._pending_directory is not None:
            import shlex

            command = (
                f"cd -- {shlex.quote(self._pending_directory)} && {{\n{command}\n}}"
            )
        get_pwd_command = f"{command};" + r'printf "\e]2025;$(pwd);\e\\"' + "\n"
        await self.write(get_pwd_command, hide_echo=True)

    async def change_directory(self, path: str) -> None:
        """Move an idle shell now, or apply the change before its next command."""
        import shlex

        self.working_directory = path
        self._pending_directory = path
        await self.wait_for_ready()
        if not await self.is_busy():
            await self.write(
                f"cd -- {shlex.quote(path)};" + r'printf "\e]2025;$(pwd);\e\\"' + "\n",
                hide_echo=True,
                hide_output=True,
            )

    async def send_input(self, text: str, paste: bool = False) -> None:
        await self.wait_for_ready()
        if paste and self.output is not None and self.output.state.bracketed_paste:
            text = f"\x1b[200~{text}\x1b[201~"
        await self.write(f"{text}\n", hide_echo=True)

    def start(self, binding: SurfaceBinding) -> None:
        self.surface = binding
        binding.prepare_shell(self)
        self._operation = self._operation.start(self)
        logging.getLogger(__name__).debug("shell starting")

    async def interrupt(self) -> None:
        """Interrupt the running command."""
        await self.write(b"\x03")

    def update_size(self, width: int, height: int) -> None:
        """Update the size of the shell pty.

        Args:
            width: Desired width.
            height: Desired height.
        """
        self._terminal_size = width, height
        if self.output is not None:
            self.output.state.update_size(width, height)
        self._operation.resize(width, max(height, 1))

    async def write(
        self, text: str | bytes, hide_echo: bool = False, hide_output: bool = False
    ) -> int:
        text_bytes = text.encode("utf-8", "ignore") if isinstance(text, str) else text

        if hide_echo:
            for line in text_bytes.split(b"\n"):
                if line:
                    self._hide_echo.add(line)
        result = await self._operation.write(text_bytes)
        self._hide_output = hide_output
        return result

    async def _run_pty(self, ready):
        current_directory = self.working_directory
        command = Command.for_script(
            self.shell or TerminalEnvironment.login_shell(os.environ),
            cwd=current_directory,
        )
        # Existing typed child initialization performs TTY acquisition AFTER
        # exec, in the SAME identity-bound child, never Python preexec_fn.
        launch = ControllingTerminalCommand(command.shell_command)
        BUFFER_SIZE = 64 * 1024
        async with AsyncExitStack() as custody:
            acquired = await PtyProcess.acquire(
                launch.argv(), env=command.env, cwd=command.cwd,
                width=self._terminal_size[0], height=max(self._terminal_size[1], 1),
                custody=custody, buffer_size=BUFFER_SIZE,
            )
            ready.set_result(acquired)
            if shell_start := self.shell_start.strip():
                shell_start = self.shell_start.strip()
                if not shell_start.endswith("\n"):
                    shell_start += "\n"
                await self.write(shell_start, hide_echo=False, hide_output=self.hide_start)

            unicode_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            while True:
                data = await shell_read(acquired.reader, BUFFER_SIZE)

                for string_bytes in list(self._hide_echo):
                    remove_bytes = string_bytes
                    if remove_bytes in data:
                        remove_start = data.index(remove_bytes)
                        try:
                            next_line = data.index(b"\n", remove_start + len(remove_bytes))
                        except ValueError:
                            data = data.replace(remove_bytes, b"\x1b[2K")
                        else:
                            data = data[:remove_start] + b"\x1b[2K" + data[next_line + 1 :]

                        self._hide_echo.discard(string_bytes)

                if line := unicode_decoder.decode(data, final=not data):
                    if self.output is None or self.output.finalized:
                        self.output = ShellTerminalOutput(ansi.TerminalState(
                            self.write, width=self._terminal_size[0], height=self._terminal_size[1]
                        ))
                        self.outputs.append(self.output)
                    output = self.output
                    scrollback, alternate = await output.state.write(
                        line, hide_output=self._hide_output
                    )
                    new_directory = output.state.current_directory
                    if new_directory:
                        output.finalized = True
                    await self._present(output)
                    output.project(scrollback, alternate)
                    if new_directory == self._pending_directory:
                        self._pending_directory = None
                    if new_directory and new_directory != current_directory:
                        current_directory = self.working_directory = new_directory
                        self.events.publish(CurrentWorkingDirectoryChanged(new_directory))
                    if output.finalized and output.state.scrollback_buffer.is_blank:
                        output.finalize()
                        self.outputs.remove(output)
                        self.output = None

                if not data:
                    break

            return TerminalCompletion.capture(await acquired.child.wait())
