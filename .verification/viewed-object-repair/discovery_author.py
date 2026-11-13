import json
from pathlib import Path
root=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source=s))
f='src/toad/settings_scope.py'
insert(f,'ConversationSettingsScope','''    async def configuration_action_panels(self):
        """Backend configuration is absent unless the viewed object supplies targets."""
        return ()

''')
# insertion before a class is module scope; insert method within the owning class instead.
ops[-1]['target_qualname']='ViewSettingsScope.configuration_panels'
ops[-1]['operation']='insert_after_target'
f='src/toad/configured_view.py'
imp(f,'from toad.widgets.comms_command_dialog import CommandForm')
imp(f,'from toad.thread_actions import ThreadAction')
insert(f,'ObjectConfigurationDialog','''class ActionProperties(CommandForm, SidebarPanelWidget):
    """The original backend operation form, using its original target writer."""

    def __init__(self, context, definition, fields):
        self.context = context
        super().__init__(definition, context.title, fields, context.observed.core)

    @property
    def panel_identity(self):
        return self.definition.declaration

    async def submit(self, arguments):
        await ThreadAction.submit(self.context, self.definition, arguments)


''')
patch(f,'ObjectConfigurationDialog.__init__','def __init__(self, panels):','def __init__(self, view):')
patch(f,'ObjectConfigurationDialog.__init__','PanelMenu(panels, SidebarState())','PanelMenu(view.configuration_panels, SidebarState(), view)')
patch(f,'ConfiguredView.open_configuration','ObjectConfigurationDialog(self.configuration_panels)','ObjectConfigurationDialog(self)')
f='src/toad/navigation_target.py'
insert(f,'NavigationTarget.matches','''    def configuration_contexts(self, view):
        """A destination without a configurable subject supplies no command context."""
        return ()

''')
insert(f,'ThreadTarget','''class ConfigurationTarget:
    """Named thread and history destinations borrow Core's configuration membership."""

    def configuration_contexts(self, view):
        navigation = view.navigation_context
        observed = view.app.coordination_access.observing(view.coordination_root)
        return (TargetContext(view.app, observed, CommandTarget.named(self.name),
                              navigation.actor, navigation.project_path,
                              navigation.owner_mode),)


''')
patch(f,'ThreadTarget','class ThreadTarget(NavigationTarget):','class ThreadTarget(ConfigurationTarget, NavigationTarget):')
patch(f,'HistoryTarget','class HistoryTarget(HistoryRoute, NavigationTarget):','class HistoryTarget(ConfigurationTarget, HistoryRoute, NavigationTarget):')
f='src/toad/screens/session_view.py'
imp(f,'from toad.configured_view import ActionProperties')
insert(f,'SidebarSessionView.paint_background','''    async def configuration_action_panels(self):
        def read():
            entries = []
            for context in self.navigation_target.configuration_contexts(self):
                for action in context.available_actions():
                    for configuration in action.declaration.configuration_actions(action):
                        entries.append((context, configuration, configuration.editable_fields))
            return entries
        declarations = await self.app.preparation.run_thread(read)
        return tuple(SideBar.Panel(action.label, ActionProperties(context, action, fields), flex=True)
                     for context, action, fields in declarations)

''')
# The paint_background property decorator must stay on its original method.
# insert_before_target inserts before decorators, leaving the added method undecorated.
f='src/toad/widgets/side_bar.py'
patch(f,'PanelMenu.__init__','def __init__(self, entries, navigation: SidebarState):','def __init__(self, entries, navigation: SidebarState, scope: ViewSettingsScope):')
patch(f,'PanelMenu.__init__','self.navigation = navigation','self.navigation = navigation\n        self.scope = scope')
patch(f,'PanelMenu.open_selection','await self.show_panel(self.picker.value)','await self.show_panel(self.picker.value)\n        self.run_worker(self.load_configuration(), group="configuration-panels", exclusive=True)')
insert(f,'PanelMenu.selection_changed','''    async def load_configuration(self):
        try:
            entries = await self.scope.configuration_action_panels()
        except Exception as error:
            self.app.show_error(error, "Object settings")
            return
        if not self.is_attached:
            return
        selected = self.picker.value
        self.entries += tuple(entries)
        with self.prevent(widgets.Select.Changed):
            self.picker.set_options((entry.title, entry) for entry in self.entries)
            self.picker.value = selected

''')
# No broad catch: use the original backend error family only.
ops[-1]['source']=ops[-1]['source'].replace('except Exception as error:', 'except CLI_FAILURES as error:')
imp(f,'from agent_comms.cli_support.cli_failures import CLI_FAILURES')
patch(f,'ThreadSidebar.panel_entries','''        yield from self.query_ancestor(ViewSettingsScope).configuration_panels
        yield from super().panel_entries()''','''        yield from super().panel_entries()
        yield from self.query_ancestor(ViewSettingsScope).configuration_panels''')
patch(f,'ThreadSidebar._compose_panels','PanelMenu(self.panel_entries(), self.navigation)','PanelMenu(self.panel_entries(), self.navigation, self.query_ancestor(ViewSettingsScope))')
Path('.verification/viewed-object-repair/discovery.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'discover-configuration-on-the-actual-viewed-target','operations':ops}]},indent=2))
