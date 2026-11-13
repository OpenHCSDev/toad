import json
from pathlib import Path
r=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname=t,source=s))
f='src/toad/acp/agent_configuration.py'
patch(f,'AgentConfiguration.editing','''        declarations = [
            (f"option_{index}", setting.annotation, field(default=setting.current))
            for index, setting in enumerate(self.picker_settings)
        ]
        return ObjectState(make_dataclass("SessionConfiguration", declarations)())''','''        return self.editing_settings(self.picker_settings)

    def editing_settings(self, settings: tuple[ConfigurationSetting, ...]) -> ObjectState:
        """Project original settings without adding fields the source did not advertise."""
        declarations = [
            (f"option_{index}", setting.annotation, field(default=setting.current))
            for index, setting in enumerate(settings)
        ]
        return ObjectState(make_dataclass("SessionConfiguration", declarations)())''')
f='src/toad/widgets/model_switcher.py'
insert(f,'SessionForm.for_prompt','''    @classmethod
    def settings(cls, configuration):
        return tuple(configuration.selections.values())

''')
patch(f,'SessionForm.for_prompt','''        state = prompt.agent_binding.configuration.editing()''','''        configuration = prompt.agent_binding.configuration
        state = configuration.editing_settings(cls.settings(configuration))''')
patch(f,'SessionForm.represents','''for row in self.values.values()) == settings.picker_settings''','''for row in self.values.values()) == self.settings(settings)''')
insert(f,'PopupSessionForm.open_model','''    @classmethod
    def settings(cls, configuration):
        return configuration.picker_settings

''')
f='src/toad/configured_view.py'
ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source='from textual.widgets import Static'))
patch(f,'AgentProperties.compose','''        yield self.form''','''        if not self.form.values:
            yield Static("This session has not advertised any settings.", markup=False)
        yield self.form''')
f='src/toad/screens/main.py'
patch(f,'MainScreen.configuration_panels','''        yield from self.operational_sources.configuration_panels(self)
        yield from super().configuration_panels''','''        yield from super().configuration_panels
        yield from self.operational_sources.configuration_panels(self)''')
Path('.verification/object-settings-sources/advertisements.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'retain-empty-advertisements-and-popup-setup-as-distinct-views','operations':ops}]},indent=2))
