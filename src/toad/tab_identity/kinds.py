"""Each tab kind carries the typed key and the operation that reopens it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from agent_comms.field_codec import PathText
from agent_comms.repo import Checkout
from agent_comms.thread_identity import ThreadIncarnation

from toad.conversation_kind import ConversationKind
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
        entry = await navigation.launch_entry(
            saved.agent_identity,
            agent_session_id=saved.agent_session_id,
            session_pk=self.key,
            project=project,
        )
        if entry is None:
            raise TabTargetGone(self, f"Saved ACP agent {saved.agent_identity} is unavailable")
        return entry


@dataclass(frozen=True)
class MailboxTab(SessionTabIdentity):
    key: ThreadIncarnation
    root: str

    async def entry(self, navigation):
        return await navigation.mailbox_entry(self)

    async def history_source(self, navigation):
        # Mailbox metadata already carries the original thread identity. Its
        # history needs the owner shell, not an ACP connection or painted body.
        entry = await self.restore(navigation)
        return await navigation.app.prepare_session(entry.mode)


@dataclass(frozen=True)
class HistoryTab(TabIdentity):
    key: ConversationKind
    owner: HistoryOrigin
    root: str

    async def entry(self, navigation):
        source = await self.owner.restore(navigation)
        return await navigation.history_entry(self, source)


@dataclass(frozen=True)
class PreviewTab(TabIdentity):
    key: Annotated[Path, PathText]

    async def entry(self, navigation):
        if not await navigation.app.preparation.run_thread(self.key.exists):
            raise TabTargetGone(self, f"Preview file no longer exists: {self.key}")
        return PreviewSessionEntry.of(self, self.key, navigation.previous(self))
