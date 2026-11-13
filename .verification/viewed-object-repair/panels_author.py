import ast,json
from pathlib import Path
root=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source=s))
f='src/toad/thread_identity.py'
imp(f,'from textual.dom import DOMNode')
insert(f,'SessionIdentity','''class ThreadIdentityScope(DOMNode):
    """The thread described by a panel, independent of the composer sending identity."""

    @property
    @abstractmethod
    def sidebar_thread_identity(self) -> SessionIdentity: ...


''')
f='src/toad/session_scope.py'
imp(f,'from toad.thread_identity import ThreadIdentityScope')
patch(f,'SessionScope','class SessionScope(ProjectPathOwner, NavigationScope, ToadNode):','class SessionScope(ThreadIdentityScope, ProjectPathOwner, NavigationScope, ToadNode):')
insert(f,'SessionScope.belongs_to_wire','''    @property
    def sidebar_thread_identity(self) -> SessionIdentity:
        return self.thread_identity

''')
f='src/toad/widgets/thread_identity.py'
imp(f,'from toad.thread_identity import ThreadIdentityScope')
insert(f,'ShowsThreadIdentity._on_mount','''    @property
    def thread_identity(self) -> SessionIdentity:
        return self.query_ancestor(ThreadIdentityScope).sidebar_thread_identity

''')
patch(f,'ShowsThreadIdentity._on_mount','self.identity_changed(self.thread_view.thread_identity)','self.identity_changed(self.thread_identity)')
patch(f,'ShowsThreadIdentity.thread_identity_changed','self.identity_changed(event.view.thread_identity)','self.identity_changed(self.thread_identity)')
# Migrate every consumer of the actual panel capability, retaining existing access to session/project owners.
for f in ['src/toad/widgets/thread_comms.py','src/toad/widgets/context_explorer.py']:
 tree=ast.parse((root/f).read_text());lines=(root/f).read_text().splitlines(keepends=True)
 for cls in tree.body:
  if isinstance(cls,ast.ClassDef):
   for method in cls.body:
    if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)):
     body=''.join(lines[method.lineno-1:method.end_lineno])
     for old,new in [('self.thread_view.thread_identity','self.thread_identity'),('tree.thread_view.thread_identity','tree.thread_identity')]:
      if old in body:
       updated=body.replace(old,new)
       patch(f,cls.name+'.'+method.name,body,updated)
       body=updated
f='src/toad/widgets/session_thread_panels.py'
insert(f,'ThreadSessionPanel','''class ThreadDetailsPanel(SessionPanel, declared_name=None):
    """The original thread diagnostics shared by session and DM views."""


''')
patch(f,'ThreadSessionPanel','class ThreadSessionPanel(SessionPanel[CoordinationStatus]):','class ThreadSessionPanel(ThreadDetailsPanel, SessionPanel[CoordinationStatus]):')
patch(f,'CommsSessionPanel','class CommsSessionPanel(SessionPanel[ThreadCommsSidebar]):','class CommsSessionPanel(ThreadDetailsPanel, SessionPanel[ThreadCommsSidebar]):')
f='src/toad/widgets/session_thread_sidebar.py'
imp(f,'from toad.widgets.session_thread_panels import ThreadDetailsPanel')
imp(f,'from toad.thread_identity import ThreadIdentityScope, NoThreadIdentity')
insert(f,'SessionThreadSidebar','''class ConversationThreadSidebar(ThreadIdentityScope, LazyThreadSidebar):
    """A DM's original declared panels describe its peer; channels supply no thread."""

    def __init__(self, screen, identities):
        self.identities = identities
        self._owner = ref(screen)
        super().__init__(state=screen._thread_sidebar_state)

    @property
    def sidebar_thread_identity(self):
        return next(iter(self.identities), NoThreadIdentity())

    def make_panels(self):
        screen = self._owner()
        if screen is None:
            raise ReferenceError("The conversation sidebar owner has retired")
        return (member().compose_panel(screen) for identity in self.identities
                for member in SessionPanel.members_with(ThreadDetailsPanel))


''')
f='src/toad/conversation_kind.py'
imp(f,'from toad.thread_identity import ThreadIdentity')
insert(f,'ConversationKind.threads_needed','''    def sidebar_identities(self, root: str):
        return ()

''')
insert(f,'DmConversation.threads_needed','''    def sidebar_identities(self, root: str):
        return (ThreadIdentity(self.peer, root),)

''')
f='src/toad/screens/comms.py'
imp(f,'from toad.widgets.session_thread_sidebar import ConversationThreadSidebar')
insert(f,'CommsScreen.compose','''    def make_thread_sidebar(self):
        return ConversationThreadSidebar(self, self.conversation.sidebar_identities(self.wire_root))

''')
Path('.verification/viewed-object-repair/panels.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'restore-original-panels-on-the-viewed-thread','operations':ops}]},indent=2))
