"""Each tab kind carries the typed key and the operation that reopens it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from agent_comms.field_codec import PathText
from agent_comms.repo import Checkout
from agent_comms.thread_identity import ThreadIncarnation

from toad.conversation_kind import ConversationKind
from toad.tab_identity import SessionTabIdentity, TabIdentity, TabTargetGone
from toad.tab_identity.history_origin import HistoryOrigin


@dataclass(frozen=True)
class AcpTab(SessionTabIdentity):
    key: int

    async def restore(self, navigation) -> None:
        database = await navigation.app.get_db()
        saved = await database.session_get(self.key)
        if saved is None:
            raise TabTargetGone(self, f"Saved ACP session {self.key} no longer exists")
        try:
            project = Checkout.checked(saved.meta_json.cwd.require_present().path)
        except ValueError as error:
            raise TabTargetGone(self, f"Saved ACP session {self.key}: {error}") from error
        await navigation.launch(
            saved.agent_identity,
            agent_session_id=saved.agent_session_id,
            session_pk=self.key,
            project=project,
        )


@dataclass(frozen=True)
class MailboxTab(SessionTabIdentity):
    key: ThreadIncarnation
    root: str

    async def restore(self, navigation) -> None:
        await navigation.restore_mailbox(self)


@dataclass(frozen=True)
class HistoryTab(TabIdentity):
    key: ConversationKind
    owner: HistoryOrigin
    root: str

    async def restore(self, navigation) -> None:
        await self.owner.restore(navigation)
        await navigation.restore_history(self)


@dataclass(frozen=True)
class PreviewTab(TabIdentity):
    key: Annotated[Path, PathText]

    async def restore(self, navigation) -> None:
        if not await navigation.app.preparation.run_thread(self.key.exists):
            raise TabTargetGone(self, f"Preview file no longer exists: {self.key}")
        await navigation.preview(self.key)
