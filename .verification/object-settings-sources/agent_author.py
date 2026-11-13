import json
from pathlib import Path
r=Path.cwd(); ops=[]
def patch(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname=t,source=s))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
f='src/toad/widgets/model_switcher.py'
patch(f,'SessionModelEditor.history_scope','self.query_ancestor(ModelSwitcher).prompt.model_history_scope','self.query_ancestor(SessionForm).prompt.model_history_scope')
patch(f,'SessionModelEditor.opened','''        if self.query_ancestor(ModelSwitcher).is_open:
            self.focus_content(False)''','''        self.focus_content(False)''')
patch(f,'SessionModelEditor.connect_provider','self.publish_core(input_events.ProviderLogin())','self.query_ancestor(SessionForm).prompt.publish_core(input_events.ProviderLogin())')
patch(f,'SessionModelEditor.dismiss_control','self.query_ancestor(ModelSwitcher).dismiss_control()','self.query_ancestor(SessionForm).dismiss_control()')
insert(f,'SessionForm.represents','''    def __init__(self, state, parts, prompt):
        super().__init__(state, parts)
        self.prompt = prompt

    @classmethod
    def for_prompt(cls, prompt):
        state = prompt.agent_binding.configuration.editing()
        return cls(state, cls.field_family.of(state), prompt)

    def dismiss_control(self):
        """An inline selection leaves its form open."""

''')
patch(f,'SessionForm.values_changed','self.publish_core(setting.selection_event(field.value))','self.prompt.publish_core(setting.selection_event(field.value))')
insert(f,'ModelSwitcher','''class PopupSessionForm(SessionForm):
    """The popup adds dismissal to the same advertised settings form."""

    def dismiss_control(self):
        self.query_ancestor(ModelSwitcher).dismiss_control()


''')
patch(f,'ModelSwitcher.compose_content','SessionForm.whole(self.prompt.agent_binding.configuration.editing())','PopupSessionForm.for_prompt(self.prompt)')
f='src/toad/configured_view.py'
imp(f,'from toad.widgets.model_switcher import SessionForm')
imp(f,'from toad.core_event_carrier import CoreEventReceiver')
imp(f,'from toad.core.events import ConfigurationChanged')
imp(f,'from metaclass_registry.mro_dispatch import handles')
imp(f,'from textual import work')
insert(f,'ObjectConfigurationDialog','''class AgentProperties(CoreEventReceiver, FillHeight, SidebarPanelWidget):
    """The selected native session's advertisements, using its original writer."""

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.listen(events.Mount, self.follow_binding)

    @classmethod
    def panel(cls, view):
        return SideBar.Panel("Agent settings", cls(view), id="agent-settings", flex=True)

    def compose(self):
        self.form = SessionForm.for_prompt(self.view.conversation.prompt)
        yield self.form

    def follow_binding(self):
        self.watch(self.view.conversation, "agent_binding", self.binding_changed)

    def binding_changed(self, old, new):
        self.retire_core_observations(old.events)
        self.observe_core(new.events)
        self.configuration_changed()

    @handles(ConfigurationChanged)
    def configuration_changed(self):
        if self.is_mounted:
            self.rebuild_form()

    @work(exclusive=True, group="agent-settings")
    async def rebuild_form(self):
        await self.recompose()

    def finish(self):
        self.form.finish()


''')
f='src/toad/agent_binding.py'
imp(f,'from toad.core.events import CoreEventStream')
insert(f,'NoAgentConnection.presentation','''    @cached_property
    def events(self):
        return CoreEventStream(self)

''')
f='src/toad/screens/main.py'
insert(f,'MainScreen.keyboard_scopes','''    @property
    def configuration_panels(self):
        yield from self.operational_sources.configuration_panels(self)
        yield from super().configuration_panels

''')
f='src/toad/session_presentation.py'
imp(f,'from toad.configured_view import AgentProperties')
insert(f,'OperationalSessionSources.prompt','''    def configuration_panels(self, view):
        yield AgentProperties.panel(view)

''')
insert(f,'MailboxSessionSources.prompt','''    def configuration_panels(self, view):
        """A mailbox has no native session configuration to advertise."""
        return ()

''')
f='src/toad/forms/object_configuration.py'
patch(f,'ObjectFieldView','''    @classmethod
    def admits(cls, field):
        return True''','')
Path('.verification/object-settings-sources/agent.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'share-the-advertised-form-with-view-properties','operations':ops}]},indent=2))
