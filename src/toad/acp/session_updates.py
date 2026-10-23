"""Process ACP notifications in order; update declarations own their effects."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING

from acp.schema import (
    AgentMessageChunk,
    AgentPlanContentUpdate,
    AgentPlanRemovedUpdate,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    SessionInfoUpdate,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)
from agent_comms.acp_extension import AgentCommsUpdate
from agent_comms.mro_dispatch import MroDispatch, handles

from toad.acp.client_session import ClientRequestOwner, ClientSessionRequest
from toad.acp.context_measurement import ContextMeasurement
from toad.acp.sdk_boundary import ValidateSessionUpdateTask
from toad.core import events
from toad.plan import decode_plan
from toad.project_link import AcpLogLink

if TYPE_CHECKING:
    from toad.acp.agent import Agent
    from toad.acp.comms_updates import CommsUpdateConsumer


class SessionUpdateEffect(MroDispatch):
    """Effect registrations consume official SDK declarations, never raw shapes."""

    def __init__(self, agent: Agent, consumer: CommsUpdateConsumer):
        self.agent, self.consumer = agent, consumer

    @property
    def route(self):
        return self.consumer.route

    def require_supported(
        self,
        update: (
            UserMessageChunk
            | AgentMessageChunk
            | AgentThoughtChunk
            | ToolCallStart
            | ToolCallProgress
            | AgentPlanUpdate
            | AgentPlanContentUpdate
            | AgentPlanRemovedUpdate
            | AvailableCommandsUpdate
            | CurrentModeUpdate
            | ConfigOptionUpdate
            | SessionInfoUpdate
            | UsageUpdate
        ),
    ):
        if not any(self.handlers_for(update)):
            raise ValueError(f"ACP update capability is not supported: {type(update).__name__}")

    @handles(UserMessageChunk)
    def user(self, update: UserMessageChunk):
        UserContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(AgentMessageChunk)
    def message(self, update: AgentMessageChunk):
        AgentContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(AgentThoughtChunk)
    def thought(self, update: AgentThoughtChunk):
        ThoughtContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(ToolCallStart)
    def tool_start(self, update: ToolCallStart):
        self.agent.tools.begin(update)

    @handles(ToolCallProgress)
    def tool_progress(self, update: ToolCallProgress):
        self.agent.tools.update(update)

    @handles(AgentPlanUpdate)
    def plan(self, update: AgentPlanUpdate):
        self.agent.controller.publish_plan(decode_plan(update.entries))

    @handles(AvailableCommandsUpdate)
    def commands(self, update: AvailableCommandsUpdate):
        self.agent.controller.publish_commands(update.available_commands)

    @handles(CurrentModeUpdate)
    def mode(self, update: CurrentModeUpdate):
        self.agent.configuration.receive_current_mode(update.current_mode_id)

    @handles(ConfigOptionUpdate)
    def config(self, update: ConfigOptionUpdate):
        self.agent.configuration.receive(update.config_options)

    @handles(SessionInfoUpdate)
    def info(self, update: SessionInfoUpdate):
        if "title" in update.model_fields_set:
            self.agent.events.publish(events.SessionInfoUpdate(update.title))

    @handles(UsageUpdate)
    def usage(self, update: UsageUpdate):
        self.agent.context_measurement = ContextMeasurement.live(update.used, update.size, update.cost)
        self.agent.update_status_line()


class MessageContentEffect(MroDispatch):
    def __init__(self, agent: Agent, route):
        self.agent, self.route = agent, route

    @handles(TextContentBlock)
    def text(self, content: TextContentBlock):
        if content.text:
            self.publish(content)

    @abstractmethod
    def publish(self, content: TextContentBlock): ...


class UserContentEffect(MessageContentEffect):
    def publish(self, content: TextContentBlock):
        self.agent.events.publish(events.UserMessage(content.type, content.text))


class ThoughtContentEffect(MessageContentEffect):
    def publish(self, content: TextContentBlock):
        self.agent.events.publish(events.Thinking(content.type, content.text))


class AgentContentEffect(MessageContentEffect):
    def publish(self, content: TextContentBlock):
        text = content.text
        if text.startswith("[agent error]"):
            text += f"\n\n{AcpLogLink.markdown(self.agent.presentation.log_path)}"
        from toad.response_delivery import ResponseDelivery

        stream = self.agent.presentation.turns.owner.response_stream(ResponseDelivery.from_route(self.route))
        self.agent.events.publish(events.Update(content.type, text, stream))


class SessionNotificationOwner(ClientRequestOwner):
    def __init__(self, agent: Agent):
        super().__init__(agent)
        self.lock = asyncio.Lock()

    async def receive(self, notification, raw_update):
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        async with self.lock:
            if authority.retired or not authority.binding.accepts_notification(notification.session_id):
                return
            validation = await self.agent.controller.task_runner.run(
                ValidateSessionUpdateTask(notification, raw_update)
            )
            if authority.retired:
                return
            validation.publish(self, notification.session_id, raw_update, notification.field_meta)

    def reject(self, session_id: str, update, metadata, error: str):
        self.agent.log(
            f"[ACP rejected session/update] raw={{'sessionId': {session_id!r}, "
            f"'update': {update!r}, '_meta': {metadata!r}}}; validation={error}"
        )
        self.agent.events.publish(events.RejectedSessionUpdate())

    def publish(self, session_id: str, update: SessionNotification, facts: tuple[AgentCommsUpdate, ...]):
        metadata = update.update.field_meta
        consumer = self.agent.comms_consumer_class(self.agent, session_id)
        effect = SessionUpdateEffect(self.agent, consumer)
        try:
            effect.require_supported(update.update)
        except (TypeError, ValueError) as error:
            self.reject(session_id, update, metadata, str(error))
            return
        for fact in facts:
            consumer.dispatch_sync(fact)
        effect.dispatch_sync(update.update)
