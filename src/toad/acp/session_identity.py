"""Session keys are independent of binding output and readiness lifetimes."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from acp.exceptions import RequestError
from agent_comms.nominal.field_codec import AcpSessionId


class SessionIdentity:
    """An unbound identity supplies no key and cannot join a shared process."""

    @property
    def bound(self) -> bool:
        return False

    def require_session_id(self) -> AcpSessionId:
        raise RequestError.invalid_params({'details': 'ACP request has no bound session'})

    def accepts_notification(self, session_id: AcpSessionId) -> bool:
        return False

    def accepts_unbound(self) -> bool:
        return True

    def matches(self, current: SessionIdentity) -> bool:
        return current.accepts_unbound()

    def available_in(self, identities: Iterable[SessionIdentity]) -> bool:
        return False


@dataclass(frozen=True)
class KnownSessionIdentity(SessionIdentity):
    """An expected key, without allocating a binding's independent output."""

    identity: AcpSessionId

    @property
    def session_id(self) -> AcpSessionId:
        return self.identity

    @property
    def bound(self) -> bool:
        return True

    def require_session_id(self) -> AcpSessionId:
        return self.identity

    def accepts_notification(self, session_id: AcpSessionId) -> bool:
        return self.identity == session_id

    def accepts_unbound(self) -> bool:
        return False

    def matches(self, current: SessionIdentity) -> bool:
        return current.accepts_notification(self.identity)

    def available_in(self, identities: Iterable[SessionIdentity]) -> bool:
        return all(not identity.accepts_notification(self.identity) for identity in identities)
