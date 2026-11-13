import json
from pathlib import Path
root=Path.cwd(); ops=[]
def p(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def ins(f,t,s): ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
f='src/toad/widgets/side_bar.py'
ins(f,'SidebarPanelWidget','''class SidebarPanelHost(Widget):
    """A panel's actual host owns whether its content is presented."""

    @property
    def panel_visible(self):
        return self.is_attached and all(node.display for node in self.walk_ancestors(with_self=True)
                                        if isinstance(node, Widget))

    @abstractmethod
    def reveal(self): ...


''')
p(f,'SideBarCollapsible','''class SideBarCollapsible(
    FillWidth,''','''class SideBarCollapsible(
    SidebarPanelHost,
    FillWidth,''')
ins(f,'SideBarCollapsible.__init__','''    @property
    def panel_visible(self):
        return super().panel_visible and not self.collapsed

    def reveal(self):
        self.collapsed = False
''')
ins(f,'SidebarVisibilityObserver.scroll_container','''    @property
    def panel_visible(self):
        return self.query_ancestor(SidebarPanelHost).panel_visible
''')
p(f,'PanelPage','''class PanelPage(FillHeight, containers.Vertical):
    """The original panel and its controls, retained while another entry is selected."""''','''class PanelBody(FillHeight, containers.Vertical):
    """The space left below the selected-view menu."""


class PanelPage(SidebarPanelHost, PanelBody):
    """The original panel and its controls, retained while another entry is selected."""

    def reveal(self):
        menu = self.query_ancestor(PanelMenu)
        menu.picker.value = next(entry for entry, page in menu.pages.items() if page is self)''')
p(f,'PanelMenu.__init__','self.body = PanelPage()','self.body = PanelBody()')
f='src/toad/widgets/thread_comms.py'
for target in ['RelationshipSort.order_writer','ThreadCommsSidebar._refresh_owner']:
    src=Path(f).read_text(); # exact expressions are unique inside each native target
    p(f,target,'self.query_ancestor(SideBarCollapsible)','self.query_ancestor(SidebarPanelHost)')
p(f,'ThreadCommsSidebar._visible','and not self.query_ancestor(SideBarCollapsible).collapsed','and self.panel_visible')
p(f,'ThreadCommsSidebar._presentation_visible','and self.query_ancestor(SideBar).presentation_visible','and self.query_ancestor(SideBar).presentation_visible\n            and self.panel_visible')
p(f,'ThreadCommsSidebar.accepts_observation','return self.model_state.serves(identity.root_path)','return self.panel_visible and self.model_state.serves(identity.root_path)')
ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source='from toad.widgets.side_bar import SidebarPanelHost'))
f='src/toad/widgets/context_explorer.py'
p(f,'ContextExplorer.presentation_visible','and not self.query_ancestor(SideBarCollapsible).collapsed','and self.panel_visible')
f='src/toad/widgets/project_panel.py'
p(f,'ProjectPanel._ensure_tree','''        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        if not self.is_attached:
            return
        sidebar = next((node for node in self.ancestors if isinstance(node, SideBar)), None)
        panel = next((node for node in self.ancestors if isinstance(node, SideBarCollapsible)), None)
        if sidebar is None or panel is None or sidebar.collapsed or panel.collapsed:
            return''','''        if not self.is_attached or not self.query_ancestor(SidebarPanelHost).panel_visible:
            return''')
ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source='from toad.widgets.side_bar import SidebarPanelHost'))
Path('.verification/view-sidebar-discovery/hosts.plan.json').write_text(json.dumps({'stages':[{'recipes':[{'recipe_id':'panel-hosts-own-visibility','operations':ops}]},{'recipes':[{'recipe_id':'drop-obsolete-frame-imports','operations':[dict(operation='remove_import_bindings',file_path=str(root/f),bound_names=['SideBarCollapsible']) for f in ['src/toad/widgets/thread_comms.py','src/toad/widgets/context_explorer.py']]}]}]},indent=2))
