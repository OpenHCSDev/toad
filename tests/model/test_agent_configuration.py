"""Typed grouped advertisements, retained state and declaration-owned new cases."""
from acp.schema import SetSessionConfigOptionResponse
from formbridge.forms.declared_fields import DeclaredField
from objectstate import DottedFieldPath
from support.agents import RecordedEvents

from toad.acp.agent_configuration import (
    AdvertisedSetting,
    AgentConfiguration,
    ModelConfigurationSetting,
)
from toad.core.events import ConfigurationChanged


def test_configuration_owns_typed_groups_replacement_and_new_case(app_agents, tmp_path):
    agent = app_agents.detached_agent()
    changes = RecordedEvents()
    subscription = agent.events.subscribe(ConfigurationChanged, changes.receive)
    configuration = AgentConfiguration(agent)
    configuration.receive(SetSessionConfigOptionResponse.model_validate({'configOptions': [
        {'id':'native-model','name':'Model','category':'model','type':'select','currentValue':'model-a',
         'options':[{'group':'local','name':'Local','options':[{'value':'model-a','name':'Model A'}]}]},
        {'id':'native-thinking','name':'Thinking','category':'thought_level','type':'select','currentValue':'high',
         'options':[{'value':'off','name':'Off'},{'value':'high','name':'High'}]},
    ]}, strict=True).config_options)
    model = configuration.setting(ModelConfigurationSetting)
    thinking = configuration.thinking
    assert model.option.id == 'native-model' and model.current == 'model-a'
    assert model.choices[0].name == 'Model A'
    assert thinking.option.id == 'native-thinking' and thinking.current == 'high'
    configuration.receive(None)
    assert configuration.setting(ModelConfigurationSetting) is model
    configuration.publish()
    assert isinstance(changes[-1], ConfigurationChanged) and subscription.stream.publisher is agent
    assert configuration.model.selected is model.choices[0]
    configuration.receive([])
    assert not configuration.thinking.choices and configuration.thinking.current == ''
    assert isinstance(changes[-1], ConfigurationChanged) and subscription.stream.publisher is agent

    extra = AgentConfiguration(agent)
    extra.receive(SetSessionConfigOptionResponse.model_validate({'configOptions': [
        {'id': 'budget', 'name': 'Budget', 'type': 'select', 'currentValue': 'bounded',
         'options': [{'value': 'bounded', 'name': 'Bounded'}]},
        {'id': 'other-budget', 'name': 'Another budget', 'type': 'select', 'currentValue': 'free',
         'options': [{'value': 'free', 'name': 'Free'}]},
        {'id': 'enabled', 'name': 'Enabled', 'type': 'boolean', 'currentValue': True},
    ]}, strict=True).config_options)
    assert extra.named('budget').current == 'bounded'
    assert extra.named('other-budget').current == 'free'
    assert extra.named('enabled').current is True
    state = extra.editing()
    fields = [DeclaredField(state, DottedFieldPath(path)) for path in state.parameter_structure.declarations]
    advertised = {field.metadata(AdvertisedSetting).setting.option.id: field
                  for field in fields if field.metadata(AdvertisedSetting).setting.option}
    assert set(advertised) == {'budget', 'other-budget', 'enabled'}
    assert advertised['budget'].label == 'Budget'
    advertised['enabled'].edit(False)
    event = advertised['enabled'].metadata(AdvertisedSetting).setting.selection_event(False)
    assert event.setting == 'enabled' and event.value is False
    assert extra.named('enabled').current is True  # Draft editing does not invent server acceptance.
    subscription.close()


def test_an_unset_model_beside_advertised_models_runs_the_default(app_agents):
    """P585: Core advertises "Not configured" for a thread on its runtime's default
    model, and the composer refused every send while the thread ran live."""
    configuration = AgentConfiguration(app_agents.detached_agent())

    def advertise(*values):
        configuration.receive(SetSessionConfigOptionResponse.model_validate({'configOptions': [
            {'id':'ModelConfigOption','name':'Model','category':'model','type':'select','currentValue':'',
             'options':[{'value':value,'name':value or 'Not configured'} for value in values]},
        ]}, strict=True).config_options)
        return configuration.setting(ModelConfigurationSetting)

    assert not advertise('', 'openai-codex/gpt-5.4').requires_selection
    assert advertise('').requires_selection
