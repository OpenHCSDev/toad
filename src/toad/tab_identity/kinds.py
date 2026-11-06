"""Each tab kind carries the typed key and the operation that reopens it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from agent_comms.nominal.field_codec import PathText
from agent_comms.repo import Checkout
from agent_comms.thread_identity import ThreadIncarnation

from toad.conversation_kind import ConversationKind
from toad.agents import AgentNotFound
from toad.session_entry import PreviewSessionEntry
from toad.tab_identity import SessionTabIdentity, TabIdentity, TabTargetGone
from toad.tab_identity.history_origin import HistoryOrigin


@dataclass(frozen=True)
class AcpTab(SessionTabIdentity):
    key: int

    async def entry(self, navigation):
        database = await navigation.app.get_db()
        saved = await database.session_get(self.key)
        if saved is None:
            raise TabTargetGone(self, f"Saved ACP session {self.key} no longer exists")
        try:
            project = Checkout.checked(saved.meta_json.cwd.require_present().path)
        except ValueError as error:
            raise TabTargetGone(self, f"Saved ACP session {self.key}: {error}") from error
        try:
            return await navigation.launch_entry(
                saved.agent_identity,
                agent_session_id=saved.agent_session_id,
                session_pk=self.key,
                project=project,
            )
        except AgentNotFound as error:
            raise TabTargetGone(self, str(error)) from error


@dataclass(frozen=True)
class MailboxTab(SessionTabIdentity):
    key: ThreadIncarnation
    root: str

    async def entry(self, navigation):
        return await navigation.mailbox_entry(self)


@dataclass(frozen=True)
class HistoryTab(TabIdentity):
    """A conversation tab saved when it still belonged to the session that opened it. Saved
    workspaces hold these rows, so they decode; each reopens nowhere and is removed."""

    key: ConversationKind
    owner: HistoryOrigin
    root: str

    async def entry(self, navigation):
        raise TabTargetGone(self, "saved when conversation tabs belonged to a session; reopen it from the sidebar")


@dataclass(frozen=True)
class CommsTab(TabIdentity):
    """A conversation on one bus, as the owner views it."""

    key: ConversationKind
    root: str

    async def entry(self, navigation):
        return await navigation.history_entry(self)


@dataclass(frozen=True)
class PreviewTab(TabIdentity):
    key: Annotated[Path, PathText]

    async def entry(self, navigation):
        if not await navigation.app.preparation.run_thread(self.key.exists):
            raise TabTargetGone(self, f"Preview file no longer exists: {self.key}")
        return PreviewSessionEntry.of(self, self.key, navigation.app.selected_mode)
