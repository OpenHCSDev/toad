"""Consume declared Comms facts through the shared nominal dispatcher."""

from __future__ import annotations

from agent_comms.acp_extension import (
    InputFailedUpdate,
    TextRouteUpdate,
    TranscriptChangedUpdate,
    TurnSettledUpdate,
    TurnStartedUpdate,
)
from agent_comms.mro_dispatch import MroDispatch, handles

from . import messages


class CommsUpdateConsumer(MroDispatch):
    def __init__(self, agent, session_id: str):
        self.agent = agent
        self.session_id = session_id
        self.route = None

    @handles(TextRouteUpdate)
    def text_route(self, update: TextRouteUpdate) -> None:
        self.route = update.route

    @handles(InputFailedUpdate)
    def input_failed(self, update: InputFailedUpdate) -> None:
        self.agent.post_message(
            messages.InputFailed(
                update.text,
                update.failure.description,
                recover_draft=False,
                agent=self.agent,
                session_id=self.session_id,
            )
        )

    @handles(TranscriptChangedUpdate)
    def transcript_changed(self, update: TranscriptChangedUpdate) -> None:
        self.agent.post_message(messages.TranscriptChanged(update.cursor))

    @handles(TurnStartedUpdate)
    def turn_started(self, update: TurnStartedUpdate) -> None:
        agent = self.agent
        if self.session_id != agent.session_id or agent._stopping:
            return
        agent.uses_turn_events = True
        agent._active_turn_id = update.turn_id
        agent._turn_lifecycle_sequence += 1
        agent.post_message(
            messages.TurnStarted(
                update.turn_id,
                update.started_at,
                update.activity,
                update.activity_detail,
                agent=agent,
                session_id=self.session_id,
                sequence=agent._turn_lifecycle_sequence,
            )
        )

    @handles(TurnSettledUpdate)
    def turn_settled(self, update: TurnSettledUpdate) -> None:
        agent = self.agent
        if self.session_id != agent.session_id or agent._stopping:
            return
        if (
            agent._active_turn_id is not None
            and update.turn_id != agent._active_turn_id
        ):
            return
        if update.turn_id is not None:
            agent.uses_turn_events = True
        agent._active_turn_id = None
        agent._turn_lifecycle_sequence += 1
        agent.post_message(
            messages.TurnSettled(
                update.turn_id,
                agent=agent,
                session_id=self.session_id,
                sequence=agent._turn_lifecycle_sequence,
            )
        )
