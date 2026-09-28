"""One-time reviewed caller migration, not an NRA equivalence proof."""
import ast
import json
from pathlib import Path

bus = json.loads(Path('/home/ts/wt/comms-refactor-s7-wire-log-20260928/evidence/s7-wire-log/caller-map.json').read_text())['bus_members']
bus['send'] = 'publisher.publish'
c0 = json.loads(Path('/home/ts/wt/comms-c0-integration-20260928/evidence/c0-operations/caller-map.json').read_text())
comms = c0['methods'] | c0['fields']
components = set(c0['components'])

def root(node):
    return ((isinstance(node, ast.Name) and node.id in root_names) or
            (isinstance(node, ast.Attribute) and node.attr in {'_wire', 'coordination_wire', 'comms'}))

def bus_root(node):
    return isinstance(node, ast.Attribute) and node.attr == 'bus'

changes = []
for path in [*Path('src').rglob('*.py'), *Path('tests').rglob('*.py')]:
    source = path.read_text()
    tree = ast.parse(source)
    root_names = {'comms', 'live'}
    for assignment in ast.walk(tree):
        if isinstance(assignment, ast.Assign) and isinstance(assignment.value, ast.Call):
            function = assignment.value.func
            if isinstance(function, ast.Name) and function.id in {'wire', 'Comms'}:
                root_names.update(target.id for target in assignment.targets if isinstance(target, ast.Name))
    starts = [0]
    for line in source.splitlines(keepends=True): starts.append(starts[-1] + len(line))
    def end(n): return starts[n.end_lineno - 1] + n.end_col_offset
    def begin(n): return starts[n.lineno - 1] + n.col_offset
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            mapping = bus if bus_root(node.value) else comms if root(node.value) else {}
            if node.attr in mapping and not (root(node.value) and node.attr in components):
                edits.append((end(node) - len(node.attr), end(node), mapping[node.attr]))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'object' and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)):
            target, attr = node.args[:2]
            mapping = bus if bus_root(target) else comms if root(target) else {}
            if attr.value in mapping:
                owner, member = mapping[attr.value].rsplit('.', 1)
                edits.append((end(target), end(target), '.' + owner))
                edits.append((begin(attr), end(attr), repr(member)))
    for start, stop, replacement in sorted(set(edits), reverse=True):
        source = source[:start] + replacement + source[stop:]
    if edits:
        ast.parse(source)
        path.write_text(source)
        changes.append({'file': str(path), 'edits': len(edits)})
Path('evidence/s7-consumers/migration.json').write_text(json.dumps(changes, indent=2)+'\n')
print(json.dumps(changes, indent=2))
