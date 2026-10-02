from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import rich.repr
from agent_comms.acp_extension import (
    AgentCommsUpdate,
    QueueScope,
)
from textual.message import Message

from .attachment_presentation import CursorPresentation, QueuePresentation
from .permission_controller import PermissionRequest

if TYPE_CHECKING:
    from toad.live_output import OutputStream


class AgentMessage(Message):
    """Base class for agent messages."""


@dataclass
class Update(AgentMessage):
    type: str
    text: str
    stream: OutputStream
    agent: object


@dataclass
@rich.repr.auto
class RequestPermission(AgentMessage):
    request: PermissionRequest


@dataclass
class CommsUpdated(AgentMessage):
    """The exact shared record plus local attachment context."""

    update: AgentCommsUpdate | QueuePresentation | CursorPresentation
    agent: object | None = None
    session_id: str | None = None
    sequence: int | None = None
    recover_draft: bool = False
    queue_scope: QueueScope | None = None
