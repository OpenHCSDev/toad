import json
from pathlib import Path
r=Path.cwd();ops=[]
def p(f,t,a,b):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=a,new_source=b)]))
def ins(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname=t,source=s))
def i(f,s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
f='src/toad/forms/editors.py'
p(f,'ValueEditor.paint_value','self.styles.text_style = "dim" if self.previewing else ""','self.styles.text_style = "dim" if self.previewing else None')
f='src/toad/thread_identity.py'
i(f,'from agent_comms.messaging.channel_targets import IncarnationThreadTarget')
ins(f,'SessionIdentity.command_target','''    def configuration_targets(self):
        """A local or absent session is configured by its own advertisements."""
        return ()

''')
ins(f,'ThreadIdentity.thread_incarnation','''    def configuration_targets(self):
        return (IncarnationThreadTarget(self.owner),)

''')
f='src/toad/navigation_target.py'
p(f,'ConfigurationTarget.configuration_contexts','''        navigation = view.navigation_context
        observed = view.app.coordination_access.observing(view.coordination_root)
        return (TargetContext(view.app, observed, CommandTarget.named(self.name),
                              navigation.actor, navigation.project_path,
                              navigation.owner_mode),)''','''        targets = self.configuration_subjects(view)
        return tuple(TargetContext(view.app,
                                   view.app.coordination_access.observing(view.coordination_root),
                                   subject, view.navigation_context.actor,
                                   view.navigation_context.project_path,
                                   view.navigation_context.owner_mode)
                     for subject in targets)''')
ins(f,'ConfigurationTarget.configuration_contexts','''    @abstractmethod
    def configuration_subjects(self, view): ...

''')
ins(f,'ThreadTarget.open','''    def configuration_subjects(self, view):
        return view.thread_identity.configuration_targets()

''')
ins(f,'HistoryTarget.for_name','''    def configuration_subjects(self, view):
        return (view.conversation.retained_target(),)

''')
f='tests/textual/test_sidebar_projection.py'
p(f,'test_view_menu_discovers_settings_and_keeps_each_objects_state',"""    preview.write_text('A viewed file\\n')
    async with""","""    preview.write_text('A viewed file\\n')
    peer = workspace.thread('panel-owner')
    from agent_comms.team.pi_rule_gate import PiRedeal
    deal = PiRedeal.of(workspace.comms, peer)
    deal.start()
    async with""")
p(f,'test_view_menu_discovers_settings_and_keeps_each_objects_state',"""        peer = workspace.thread('panel-owner')
        from agent_comms.team.pi_rule_gate import PiRedeal
        deal = PiRedeal.of(workspace.comms, peer)
        deal.start()
""",'')
Path('.verification/viewed-object-repair/target.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'preserve-subject-birth-and-local-session-ownership','operations':ops}]},indent=2))
