"""Typed grouped advertisements, retained state and declaration-owned new cases."""
from acp.schema import SessionConfigOptionSelect
from toad.acp.agent_configuration import (AgentConfiguration, ConfigurationSetting,
                                         ModelConfigurationSetting, ThinkingConfigurationSetting)

class Publication:
    def __init__(self):
        self.messages = []
    def post_message(self, value):
        self.messages.append(value)


def test_configuration_owns_typed_groups_replacement_and_new_case():
    agent = Publication()
    configuration = AgentConfiguration(agent)
    configuration.receive({'configOptions': [
        {'id':'native-model','name':'Model','category':'model','type':'select','currentValue':'model-a',
         'options':[{'group':'local','name':'Local','options':[{'value':'model-a','name':'Model A'}]}]},
        {'id':'native-thinking','name':'Thinking','category':'thought_level','type':'select','currentValue':'high',
         'options':[{'value':'off','name':'Off'},{'value':'high','name':'High'}]},
    ]})
    model = configuration.setting(ModelConfigurationSetting)
    thinking = configuration.thinking
    assert model.option.id == 'native-model' and model.current == 'model-a'
    assert model.choices[0].name == 'Model A'
    assert thinking.option.id == 'native-thinking' and thinking.current == 'high'
    configuration.receive({})
    assert configuration.setting(ModelConfigurationSetting) is model
    configuration.publish()
    assert agent.messages[-2].models['model-a'].name == 'Model A'
    assert agent.messages[-1].current_level == 'high'
    configuration.receive({'configOptions':[]})
    assert not configuration.thinking.choices and configuration.thinking.current == ''
    assert agent.messages[-1].current_level == ''  # unavailable never invented off

    class BudgetConfigurationSetting(ConfigurationSetting):
        label = 'budget'
        @classmethod
        def matches(cls, option):
            return option.id == 'budget'
        def publish(self, agent):
            agent.post_message(self.current)

    try:
        extra = AgentConfiguration(agent)
        extra.receive({'configOptions':[{'id':'budget','name':'Budget','type':'select','currentValue':'bounded',
                                        'options':[{'value':'bounded','name':'Bounded'}]}]})
        assert extra.setting(BudgetConfigurationSetting).current == 'bounded'
        assert 'bounded' in agent.messages
    finally:
        ConfigurationSetting.__registry__.pop(BudgetConfigurationSetting.declared_name)
