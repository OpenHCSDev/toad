"""Declared copy transports; platform selection is a single boundary operation."""

import asyncio
from abc import abstractmethod
from collections.abc import Callable

from agent_comms.declared_family import DeclaredFamily
from pyperclip import PyperclipException
from textual.app import App


class Clipboard(DeclaredFamily, affix="Clipboard"):
    @classmethod
    def for_platform(cls) -> Clipboard:
        import pyperclip

        native_copy, native_paste = pyperclip.determine_clipboard()
        return (
            SystemClipboard(native_copy, native_paste)
            if native_copy
            else TerminalClipboard()
        )

    def copy(self, app: App, text: str) -> Clipboard:
        transport = self.publish(app, text)
        # This is Textual's existing local-value authority, not another cache.
        app._clipboard = text
        return transport

    @abstractmethod
    def publish(self, app: App, text: str) -> Clipboard: ...

    def read(self, app: App) -> str:
        return app.clipboard

    async def paste(self, app: App) -> str:
        return await asyncio.to_thread(self.read, app)


class SystemClipboard(Clipboard):
    def __init__(
        self, native_copy: Callable[[str], None], native_paste: Callable[[], str]
    ) -> None:
        self.native_copy = native_copy
        self.native_paste = native_paste

    def publish(self, app: App, text: str) -> Clipboard:
        try:
            self.native_copy(text)
        except OSError, PyperclipException:
            return TerminalClipboard().publish(app, text)
        return self

    def read(self, app: App) -> str:
        try:
            return self.native_paste()
        except OSError, PyperclipException:
            return super().read(app)


class TerminalClipboard(Clipboard):
    def publish(self, app: App, text: str) -> Clipboard:
        App.copy_to_clipboard(app, text)
        return self
