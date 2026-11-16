"""The Textual app's session entries: each builds the screen for the tab identities it shows.

The shared entries in `toad.client` own identity, projection and lifetime; a member here
adds only its Textual view, and the app selects it through `TextualSessionEntry`.
"""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout

from toad.acp.agent_log import AgentLog
from toad.client.history_entry import HistorySessionEntry
from toad.client.session_entry import (
    AcpLogSessionEntry,
    NativeSessionEntry,
    PreviewSessionEntry,
)
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab, PreviewTab
from toad.launch_binding import AgentBinding
from toad.screens.comms import CommsScreen
from toad.screens.file_preview import FilePreviewScreen
from toad.screens.main import MainScreen
from toad.session_host import SessionEntries, SessionNavigator
from toad.widgets.acp_log import AcpLogPreview
from toad.widgets.project_panel import FilePreview


class TextualSessionEntry(SessionEntries):
    """The Textual app's entry family."""


class TextualNativeSessionEntry(TextualSessionEntry, NativeSessionEntry, shows=(SessionTabIdentity,)):
    """An agent or mailbox session, viewed in a Textual MainScreen."""

    @staticmethod
    def session_view(
        project: Checkout,
        binding: AgentBinding,
        *,
        session_pk: int,
        initial_prompt: str | None = None,
    ) -> MainScreen:
        return MainScreen(project, binding, session_pk=session_pk, initial_prompt=initial_prompt)


class TextualHistorySessionEntry(TextualSessionEntry, HistorySessionEntry, shows=(CommsTab,)):
    """The shared conversation entry, viewed in a Textual CommsScreen."""

    def __call__(self, sessions: SessionNavigator):

        key = self.key
        return CommsScreen(
            project_path=self.project,
            me=self.viewer,
            conversation=key.conversation,
            wire_root=key.root,
        )


class TextualPreviewSessionEntry(TextualSessionEntry, PreviewSessionEntry, shows=(PreviewTab,)):
    """A read-only file, viewed in a Textual FilePreviewScreen."""

    def __call__(self, sessions: SessionNavigator):

        return FilePreviewScreen(self.path, self.content)

    def content(self):

        return FilePreview(self.path)


class TextualAcpLogSessionEntry(TextualPreviewSessionEntry, AcpLogSessionEntry, shows=(AgentLog,)):
    """An agent's ACP log, viewed in a Textual FilePreviewScreen."""

    def content(self):

        return AcpLogPreview(self.path)
