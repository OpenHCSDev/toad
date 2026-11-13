import json
from pathlib import Path
r=Path.cwd();ops=[]
def p(f,t,a,b):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=a,new_source=b)]))
def i(f,s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
p('src/toad/conversation_kind.py','ConversationKind.sidebar_identities','def sidebar_identities(self, root: str):','def sidebar_threads(self):')
p('src/toad/conversation_kind.py','DmConversation.sidebar_identities','''    def sidebar_identities(self, root: str):
        return (ThreadIdentity(self.peer, root),)''','''    def sidebar_threads(self):
        return (self.peer,)''')
p('src/toad/screens/comms.py','CommsScreen.make_thread_sidebar','self.conversation.sidebar_identities(self.wire_root)','self.conversation.sidebar_threads()')
p('src/toad/widgets/session_thread_sidebar.py','ConversationThreadSidebar.__init__','''    def __init__(self, screen, identities):
        self.identities = identities''','''    def __init__(self, screen, threads):
        self.identities = tuple(ThreadIdentity(thread, screen.wire_root) for thread in threads)''')
i('src/toad/widgets/session_thread_sidebar.py','from toad.thread_identity import ThreadIdentity')
Path('.verification/viewed-object-repair/cycle.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'keep-conversation-subjects-below-panel-presentation','operations':ops}]},indent=2))
