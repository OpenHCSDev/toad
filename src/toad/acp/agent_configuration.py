"""Typed ACP advertisements own their selection, publication and request behavior."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from acp.schema import (SessionConfigSelectOption, SessionConfigSelectGroup,
                        SessionConfigOptionSelect, SetSessionConfigOptionResponse)
from agent_comms.acp_failure import ACPFailure
from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import MroDispatch, handles
from toad import jsonrpc
from toad.acp import api, messages


class SelectChoices(MroDispatch):
    """Flatten only the SDK's decoded external flat/group variants."""
    def __init__(self, option: SessionConfigOptionSelect):
        self.values: list[SessionConfigSelectOption] = []
        for value in option.options:
            self.dispatch_sync(value)

    @handles(SessionConfigSelectOption)
    def choice(self, value):
        self.values.append(value)

    @handles(SessionConfigSelectGroup)
    def group(self, value):
        self.values.extend(value.options)


@dataclass(frozen=True)
class ConfigurationSetting(DeclaredFamily, affix="ConfigurationSetting"):
    option: SessionConfigOptionSelect | None = None
    label: ClassVar[str]

    @classmethod
    @abstractmethod
    def matches(cls, option: SessionConfigOptionSelect) -> bool: ...

    @classmethod
    def bind(cls, option):
        if option.current_value not in {value.value for value in SelectChoices(option).values}:
            raise ValueError(f"ACP configuration {option.id!r} has no advertised current value")
        return cls(option)

    @property
    def current(self) -> str:
        return self.option.current_value if self.option else ""

    @property
    def choices(self) -> tuple[SessionConfigSelectOption, ...]:
        return tuple(SelectChoices(self.option).values) if self.option else ()

    async def select(self, agent, value: str) -> str | None:
        if self.option is None:
            return f"This agent does not advertise {self.label} configuration"
        with agent.request():
            response = api.session_set_config_option(agent.session_id, self.option.id, value)
        try:
            result = await response.wait()
        except jsonrpc.JSONRPCError as error:
            return ACPFailure.from_error(error.code, error.message).feedback
        except jsonrpc.APIError as error:
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
        if result is not None:
            agent.configuration.receive(result)
        return None

    @abstractmethod
    def publish(self, agent) -> None: ...


class ModelConfigurationSetting(ConfigurationSetting):
    label = "model"

    @classmethod
    def matches(cls, option):
        return option.category == "model" or option.id == "model"

    def publish(self, agent):
        from toad.acp.agent import Model
        models = {choice.value: Model(choice.value, choice.name, choice.description)
                  for choice in self.choices}
        agent.post_message(messages.SetModels(self.current, models))


class ThinkingConfigurationSetting(ConfigurationSetting):
    label = "thinking-level"

    @classmethod
    def matches(cls, option):
        return option.category == "thought_level" or option.id == "thinking_level"

    def publish(self, agent):
        agent.post_message(messages.SetThinkingLevels(self.current, [choice.value for choice in self.choices]))


class ConfigurationAdvertisements(MroDispatch):
    def __init__(self, selections):
        self.selections = selections

    @handles(SessionConfigOptionSelect)
    def selection(self, option):
        for kind in ConfigurationSetting.members_with(ConfigurationSetting):
            if kind.matches(option):
                self.selections[kind] = kind.bind(option)
                return


class AgentConfiguration:
    """Single actual advertisement owner; detached surfaces keep this same value."""
    def __init__(self, agent):
        self.agent = agent
        self.selections = {kind: kind() for kind in ConfigurationSetting.members_with(ConfigurationSetting)}

    def setting[T: ConfigurationSetting](self, kind: type[T]) -> T:
        from typing import cast
        return cast(T, self.selections[kind])

    @property
    def thinking(self) -> ThinkingConfigurationSetting:
        return self.setting(ThinkingConfigurationSetting)

    def receive(self, response):
        if response.config_options is None:
            return
        # Official external decoder once; consumers use its guaranteed typed fields.
        selections = {kind: kind() for kind in ConfigurationSetting.members_with(ConfigurationSetting)}
        decoder = ConfigurationAdvertisements(selections)
        for option in response.config_options:
            decoder.dispatch_sync(option)
        self.selections = selections
        self.publish()

    def publish(self):
        for setting in self.selections.values():
            setting.publish(self.agent)
