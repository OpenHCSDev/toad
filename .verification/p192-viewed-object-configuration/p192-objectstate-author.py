import ast,json
from pathlib import Path
r=Path('/home/ts/wt/codex-live--P192--objectstate');file=r/'src/objectstate/context_manager.py';s=file.read_text();n=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=='extract_all_configs');old=ast.get_source_segment(s,n)
new='''def extract_all_configs(context_obj) -> Dict[type, Any]:
    """Read every declared nested configuration, retaining its nominal identity.

    Each stored object is visited once. Repeated paths to the same object are
    shared; different objects claiming the same config type still refuse.
    Stored values are read without invoking lazy resolution in the layer being built.
    """
    configs: Dict[type, Any] = {}
    pending = deque([(context_obj, "context object")])
    visited: set[int] = set()
    while pending:
        current, source = pending.popleft()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        if is_dataclass(current):
            _record_config_instance(configs, current, source=source)
            for field_name, declared_type in _declared_config_fields(type(current)):
                value = object.__getattribute__(current, field_name)
                if value is None:
                    continue
                if not _is_compatible_config_type(value, declared_type):
                    raise TypeError(
                        f"{type(current).__name__}.{field_name} declares "
                        f"{declared_type.__name__}, got {type(value).__name__}."
                    )
                pending.append((value, f"{source}.{field_name}"))
        else:
            children: Dict[type, Any] = {}
            _extract_from_object_attributes_typed(current, children)
            pending.extend((child, f"{source}.{kind.__name__}")
                           for kind, child in children.items())
    return configs'''
ops=[dict(operation='ensure_import',file_path=str(file),import_source='from collections import deque'),dict(operation='patch_target',file_path=str(file),target_qualname='extract_all_configs',replacements=[dict(old_source=old,new_source=new)])]
tests='''def test_extract_all_configs_visits_nested_and_shared_records() -> None:
    @dataclass
    class Leaf:
        value: str = "original"

    @dataclass
    class Branch:
        first: Leaf
        shared: Leaf

    @dataclass
    class Root:
        branch: Branch

    leaf = Leaf()
    root = Root(Branch(leaf, leaf))
    assert extract_all_configs(root) == {Root: root, Branch: root.branch, Leaf: leaf}


def test_extract_all_configs_refuses_collision_below_a_direct_child() -> None:
    @dataclass
    class Leaf:
        value: str

    @dataclass
    class Branch:
        first: Leaf
        second: Leaf

    @dataclass
    class Root:
        branch: Branch

    with pytest.raises(ValueError, match="second Leaf instance"):
        extract_all_configs(Root(Branch(Leaf("first"), Leaf("second"))))
'''
ops.append(dict(operation='insert_after_target',file_path=str(r/'tests/test_context_manager.py'),target_qualname='test_extract_all_configs_accepts_concrete_value_for_lazy_declared_owner',source=tests))
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-objectstate.plan.json').write_text(json.dumps({'recipes':[dict(recipe_id='collect-the-entire-declared-configuration-graph',operations=ops)]},indent=2))
