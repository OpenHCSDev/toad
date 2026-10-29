"""Declared copy transports; platform selection is a single boundary operation."""

import asyncio
from abc import abstractmethod
from collections.abc import Callable

from agent_comms.nominal.declared_family import DeclaredFamily
from pyperclip import PyperclipException
from textual.app import App
from textual._clipboard import ClipboardContent


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

    @abstractmethod
    def publish(self, app: App, text: str) -> Clipboard: ...

    def read(self, app: App) -> ClipboardContent:
        return app.clipboard_content

    async def paste(self, app: App) -> ClipboardContent:
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

    def read(self, app: App) -> ClipboardContent:
        try:
            return ClipboardContent(self.native_paste())
        except OSError, PyperclipException:
            return super().read(app)


class TerminalClipboard(Clipboard):
    def publish(self, app: App, text: str) -> Clipboard:
        App.publish_clipboard(app, text)
        return self
