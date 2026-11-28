from __future__ import annotations

from dataclasses import dataclass, field

from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec, NoAcpSessionId
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transcript.transcripts import TranscriptReadIdentity
from toad.acp.session_output import SessionOutput


class SourceIdentity:
    def matches_source(self, root: str, thread: ThreadIncarnation) -> bool:
        return False


@dataclass(frozen=True)
class SessionBinding:
    """Actual ACP binding identity, preserved only until session replacement."""

    session_id: AcpSessionId | NoAcpSessionId
    output: SessionOutput = field(default_factory=SessionOutput, compare=False)

    @property
    def bound(self) -> bool:
        return self.session_id.bound

    def accepts_notification(self, session_id: AcpSessionId):
        return self.session_id == session_id

    def accepts_snapshot(
        self, identity: TranscriptReadIdentity, owner: SourceIdentity
    ) -> bool:
        return (self.accepts_notification(FieldCodec.decode(AcpSessionId, identity.requested_name))
                and owner.matches_source(identity.root, identity.thread.incarnation))
