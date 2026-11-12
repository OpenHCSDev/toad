import ast,json
from pathlib import Path
root=Path('/home/ts/wt/codex-live--P181--toad/src/toad');ops=[]
def patch(file,target,old,new):ops.append(dict(operation='patch_target',file_path=str(root/file),target_qualname=target,replacements=[dict(old_source=old,new_source=new)]))
def imp(file,source):ops.append(dict(operation='ensure_import',file_path=str(root/file),import_source=source))
patch('column_layout.py','toad.column_layout','from textual.scrollable_container import ScrollableContainer','from textual.containers import ScrollableContainer')
# The common native body owns mounting for every configured source.
ops.append(dict(operation='insert_after_target',file_path=str(root/'settings_scope.py'),target_qualname='ConversationSettingsScope',source='''class ObjectSidebarHost(Widget):
    """The native body in which a viewed object's properties are placed."""
'''))
imp('settings_scope.py','from textual.widget import Widget')
imp('screens/session_view.py','from toad.settings_scope import ObjectSidebarHost')
patch('screens/session_view.py','SessionBody','class SessionBody(WidgetView, ToadNode, Center):','class SessionBody(WidgetView, ToadNode, ObjectSidebarHost, Center):')
patch('screens/session_view.py','SidebarSessionView','def sidebars(self) -> tuple[SidebarT, ...]:','def sidebars(self) -> tuple[SideBar, ...]:')
imp('screens/file_preview.py','from toad.screens.session_view import SessionBody')
patch('screens/file_preview.py','FilePreviewScreen.compose','''        with FileContents():
            yield self.preview''','''        with SessionBody():
            with FileContents():
                yield self.preview''')
imp('configured_view.py','from toad.settings_scope import ObjectSidebarHost')
imp('configured_view.py','from toad.session_tracker import SidebarState')
patch('configured_view.py','ConfiguredView','''        return SideBar(SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state), flex=True),
                       placement_identity=ObjectSidebarPlacement, hide=True)''','''        return ObjectSidebar(SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state), flex=True),
                             state=SidebarState())''')
patch('configured_view.py','ConfiguredView','    @on(events.Unmount)','''    @on(events.Mount)
    async def mount_configuration(self):
        await self.query_one(ObjectSidebarHost).mount(self.configuration_sidebar)

    @on(events.Unmount)''')
imp('configured_view.py','from toad.widgets.side_bar import ThreadSidebar')
ops.append(dict(operation='insert_before_target',file_path=str(root/'configured_view.py'),target_qualname='ObjectProperties',source='''class ObjectSidebar(ThreadSidebar):
    placement_type = ObjectSidebarPlacement


'''))
patch('widgets/side_bar.py','ThreadSidebar','class ThreadSidebar(SideBar):','class ThreadSidebar(SideBar):\n    placement_type = ThreadSidebarPlacement\n')
patch('widgets/side_bar.py','ThreadSidebar','placement_identity=ThreadSidebarPlacement','placement_identity=self.placement_type')
# Remove the holes left by declaration relocation, keeping field source otherwise exact.
s=(root/'preferences.py').read_text();c=next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name=='UiSettings');before=ast.get_source_segment(s,c);after=before
while '\n\n\n' in after:after=after.replace('\n\n\n','\n\n')
if after!=before:patch('preferences.py','UiSettings',before,after)
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-assembly.plan.json').write_text(json.dumps({'recipes':[dict(recipe_id='native-sidebar-assembly-and-shared-placement',operations=ops)]},indent=2)+'\n')
