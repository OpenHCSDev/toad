"""A bound agent's shared surface and observation lifetime."""
from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from toad.acp.status import PromptResult
from toad.agent_binding import AgentConnection
from toad.agent_presentation import AgentPresentation, LocalAgentPresentation
from toad.core.events import CoreEventStream
from toad.surface_binding import SurfaceBinding

if TYPE_CHECKING:
    from toad.conversation_turn import TurnOwner
    from toad.session_observation import SessionObservation
    from toad.session_presentation import OperationalSessionSources
    from toad.widgets.conversation import Conversation, ConversationSessionBinding


class AgentBase(AgentConnection):
    """A connected surface; native protocol resources belong to its concrete agent."""

    def __init__(self, project_root: Path) -> None:
        self.project_root_path = project_root
        self.events = CoreEventStream(self)

    @cached_property
    def presentation(self) -> AgentPresentation:
        return LocalAgentPresentation(self)

    def attach_view(self, view: Conversation) -> None:
        from toad.agent_surface import AttachedSurfaceBinding
        from toad.core.events import SessionAgentAttached

        self.attach_surface(AttachedSurfaceBinding(view, self.events))
        view.publish_core(SessionAgentAttached())

    def matches_agent(self, agent: object) -> bool:
        return self is agent

    def cancel_allowed(self, turn: TurnOwner) -> bool:
        return turn.can_cancel

    def invalidate_observation(self, observation: SessionObservation) -> None:
        observation.schedule(self)

    @property
    def automatic_titles(self) -> bool:
        return self.observed_thread() is None

    async def project_changed(self, path: Path) -> None:
        self.project_root_path = path

    async def cancel_turn(self, view: Conversation) -> None:
        await view.cancel_bound_turn(self)

    def refresh_projection(self, view: Conversation) -> None:
        self.refresh_context(view)
        view.turns.bound()
        view.submissions.publish_pending()
        view.delivery_observation.invalidate()

    def start_session(self, view: ConversationSessionBinding) -> None:
        if self.ready:
            view.session_ready()

    def start_agent(self, sources: OperationalSessionSources, view: Conversation) -> None:
        """A connected agent is not created a second time."""

    def update_view(self, view: ConversationSessionBinding) -> None:
        view.apply_bound_agent(self)

    def connected(self, view: ConversationSessionBinding) -> None:
        view.agent_connected(self)

    def attach_surface(self, binding: SurfaceBinding) -> None:
        binding.close()

    async def retire_surface(self, surface: Conversation) -> None:
        await self.stop()

    @abstractmethod
    async def send_prompt(self, prompt: str) -> PromptResult:
        """Preserve the source's completed, failed or unconfirmed answer."""
