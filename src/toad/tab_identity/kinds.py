"""Each tab kind carries the typed key and the operation that reopens it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from agent_comms.field_codec import PathText
from agent_comms.thread_identity import ThreadIncarnation

from toad.conversation_kind import ConversationKind
from toad.tab_identity import SessionTabIdentity, TabIdentity
from toad.tab_identity.history_origin import HistoryOrigin


@dataclass(frozen=True)
class AcpTab(SessionTabIdentity):
    key: int

    async def restore(self, navigation) -> None:
        saved = await navigation.app.tab_order.db.session_get(self.key)
        if saved is None:
            navigation.app.tab_order.close((self,))
            navigation.app.log.error(f"Removed tab for missing ACP session {self.key}")
            return
        await navigation.launch(
            saved.agent_identity,
            agent_session_id=saved.agent_session_id,
            session_pk=self.key,
            project_path=saved.meta_json.cwd,
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
        await navigation.preview(self.key)
