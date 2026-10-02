"""One-off AST batch for the original event and native delivery consumer closure."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[2]
core_handlers = {'AgentReady', 'AgentFail', 'SessionChangedEvent'}
source_fields = {'update', 'session_id', 'sequence', 'recover_draft', 'queue_scope'}

for p in (root / 'src/toad').rglob('*.py'):
    if p.name in ('events.py', 'core_event_carrier.py', 'messages.py'):
        continue
    s = p.read_text()
    tree = ast.parse(s)
    lines = s.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    def span(n):
        return offsets[n.lineno-1] + n.col_offset, offsets[n.end_lineno-1] + n.end_col_offset
    edits = []
    namespaces = set()
    direct = set()
    supported = {'CommsUpdated', 'Update'}
    for n in ast.walk(tree):
        if not isinstance(n, ast.ImportFrom):
            continue
        if n.module in ('toad.acp', None) and (n.module == 'toad.acp' or n.level == 1):
            moved = [a for a in n.names if a.name == 'messages']
            if moved:
                namespaces.update(a.asname or a.name for a in moved)
                kept = [a for a in n.names if a not in moved]
                prefix = '.' * n.level + (n.module or '')
                code = '\n'.join('from toad.core import events as ' + (a.asname or a.name) for a in moved)
                if kept:
                    code += '\n' + ' ' * n.col_offset + 'from ' + prefix + ' import ' + ', '.join(a.name + (' as ' + a.asname if a.asname else '') for a in kept)
                a,b = span(n); edits.append((a,b,code))
        if n.module in ('toad.acp.messages', 'messages') and (n.module != 'messages' or n.level == 1):
            a,b = span(n)
            code = 'from toad.core.events import ' + ', '.join(a.name + (' as ' + a.asname if a.asname else '') for a in n.names)
            edits.append((a,b,code))
            direct.update(a.asname or a.name for a in n.names if a.name in supported)
    def event_kind(n):
        if not isinstance(n, ast.Call): return None
        f = n.func
        if isinstance(f, ast.Name) and f.id in direct: return f.id
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in namespaces and f.attr in supported: return f.attr
        return None
    class Publication(ast.NodeTransformer):
        def visit_Call(self, n):
            self.generic_visit(n)
            kind = event_kind(n)
            if kind == 'CommsUpdated':
                if len(n.args) > 1: del n.args[1]
                n.keywords = [k for k in n.keywords if k.arg != 'agent']
            elif kind == 'Update':
                if len(n.args) == 4: del n.args[3]
                n.keywords = [k for k in n.keywords if k.arg != 'agent']
            if isinstance(n.func, ast.Attribute) and n.func.attr in ('post', 'post_message') and n.args and event_kind(n.args[0]):
                receiver = ast.unparse(n.func.value)
                if receiver == 'binding': receiver = 'self.agent'
                if receiver == 'screen.conversation': receiver = 'agent'
                assert receiver in ('agent', 'self.agent', 'self'), (p,n.lineno,receiver)
                n.func = ast.parse(receiver + '.events.publish', mode='eval').body
            return n
    parent = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n): parent[child] = n
    selected = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        if event_kind(n):
            outer = parent.get(n)
            if isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute) and outer.func.attr in ('post','post_message'):
                n = outer
            if n not in selected: selected.append(n)
    for n in selected:
        a,b = span(n); edits.append((a,b,ast.unparse(Publication().visit(n))))
    # Native @handles selects the data type and borrows this one carrier.
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef)): continue
        is_core = any(isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id == 'handles' and any((isinstance(a,ast.Attribute) and isinstance(a.value,ast.Name) and a.value.id in ('core_events','session_requests')) or (isinstance(a,ast.Name) and a.id in core_handlers) for a in d.args) for d in n.decorator_list)
        is_comms = any(isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id == 'on' and any(isinstance(a,ast.Attribute) and isinstance(a.value,ast.Name) and a.value.id in namespaces and a.attr=='CommsUpdated' for a in d.args) for d in n.decorator_list)
        is_update = any(isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id == 'on' and any(isinstance(a,ast.Attribute) and isinstance(a.value,ast.Name) and a.value.id in namespaces and a.attr=='Update' for a in d.args) for d in n.decorator_list)
        args = n.args.args
        typed_comms = len(args) > 1 and args[1].annotation and 'CommsUpdated' in ast.unparse(args[1].annotation)
        if not (is_core or is_comms or is_update or typed_comms): continue
        assert len(args) > 1, (p,n.lineno)
        arg = args[1]
        if arg.annotation and ast.unparse(arg.annotation) == 'CoreEventMessage': continue
        if arg.annotation:
            a,b = span(arg.annotation); edits.append((a,b,'CoreEventMessage'))
        for d in n.decorator_list:
            if (is_comms or is_update) and isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=='on':
                a,b=span(d.func); edits.append((a,b,'handles'))
        for child in ast.walk(n):
            if isinstance(child,ast.Attribute) and isinstance(child.value,ast.Name) and child.value.id==arg.arg:
                if child.attr == 'agent': new = arg.arg+'.publisher'
                elif child.attr == 'stop': continue
                else: new = arg.arg+'.event.'+child.attr
                a,b=span(child); edits.append((a,b,new))
    # Source/event fields in the existing turn and submission consumers.
    if p.name in ('conversation_turn.py','conversation_submission.py'):
        for n in ast.walk(tree):
            if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='message':
                if n.attr=='agent': value='message.publisher'
                elif n.attr in source_fields: value='message.event.'+n.attr
                else: continue
                a,b=span(n); edits.append((a,b,value))
    if p.name == 'conversation.py':
        for n in ast.walk(tree):
            if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Attribute) and isinstance(n.value.value,ast.Name) and n.value.value.id=='self' and n.value.attr=='message':
                if n.attr=='agent': value='self.message.publisher'
                elif n.attr in source_fields: value='self.message.event.'+n.attr
                else: continue
                a,b=span(n); edits.append((a,b,value))
    if edits:
        edits = list(set(edits))
        ordered=sorted(edits)
        for old,new in zip(ordered,ordered[1:]):
            assert old[1] <= new[0], ('overlap',p,old,new)
        for a,b,value in sorted(edits,reverse=True): s=s[:a]+value+s[b:]
        if 'CoreEventMessage' in s and 'import CoreEventMessage' not in s:
            future='from __future__ import annotations\n'
            if future in s:
                s=s.replace(future,future+'from toad.core_event_carrier import CoreEventMessage\n',1)
            else:
                s='from toad.core_event_carrier import CoreEventMessage\n'+s
        # Preserve pure tracker/source owner construction.
        s=s.replace('CoreEventStream()', 'CoreEventStream(self)')
        p.write_text(s)
    elif 'CoreEventStream()' in s:
        p.write_text(s.replace('CoreEventStream()', 'CoreEventStream(self)'))
