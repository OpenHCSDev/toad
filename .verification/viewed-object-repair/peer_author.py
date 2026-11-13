import json
from pathlib import Path
r=Path.cwd();f='src/toad/widgets/session_thread_sidebar.py';ops=[]
def p(t,a,b):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=a,new_source=b)]))
def i(s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
i('from agent_comms.messaging.display_references import ThreadReferenceReader')
i('from toad.thread_identity import LocalThreadIdentity, SessionIdentity')
ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname='ConversationThreadSidebar',source='''class SidebarThreadIdentity(ThreadReferenceReader[SessionIdentity]):
    """A retired peer's old name must never address a replacement thread."""

    def __init__(self, root):
        self.root = root

    def current(self, reference):
        return ThreadIdentity(reference.incarnation, self.root)

    def retired(self, reference):
        return LocalThreadIdentity(f"{reference.name} (gone)")


'''))
p('ConversationThreadSidebar.__init__','self.identities = tuple(ThreadIdentity(thread, screen.wire_root) for thread in threads)','self.threads = threads')
p('ConversationThreadSidebar.sidebar_thread_identity','''        return next(iter(self.identities), NoThreadIdentity())''','''        screen = self._owner()
        if screen is None:
            raise ReferenceError("The conversation sidebar owner has retired")
        references = screen.app.coordination_access.observation.observed().sidebar.observation.thread_names()
        return next((references.thread(thread).read(SidebarThreadIdentity(screen.wire_root))
                     for thread in self.threads), NoThreadIdentity())''')
p('ConversationThreadSidebar.make_panels','for identity in self.identities','for thread in self.threads')
Path('.verification/viewed-object-repair/peer.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'retain-peer-birth-through-current-reference-resolution','operations':ops}]},indent=2))
