"""Application declarations cannot regress to root actions, stores or rosters."""
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]/'src/toad'


def test_application_action_caller_deletion():
    retired={'save_settings','_save_settings','_apply_preference','get_main_screen',
             'capture_event','run_version_check','run_on_exit','settings_path',
             'last_ctrl_c_time','update_required','version_meta','InterfaceProvider'}
    for path in ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.Attribute(attr=attr) if attr in retired:
                    raise AssertionError((path,node.lineno,attr))
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if name in retired:
                    raise AssertionError((path,node.lineno,name))
    app=next(node for node in ast.parse((ROOT/'app.py').read_text()).body
             if isinstance(node,ast.ClassDef) and node.name=='ToadApp')
    assert app.end_lineno-app.lineno+1<=500
    assert not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('action_')
                   for n in app.body)
    bindings=next(n for n in app.body if isinstance(n,ast.Assign)
                  and any(isinstance(target,ast.Name) and target.id=='BINDINGS' for target in n.targets))
    assert isinstance(bindings.value,ast.ListComp)
    assert not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCREENS'
                   for t in n.targets) for n in app.body)
    for path in ('application_actions.py','application_lifetime.py'):
        for node in ast.walk(ast.parse((ROOT/path).read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='run_worker':
                if node.args and isinstance(node.args[0],ast.Call):
                    assert isinstance(node.args[0].func,ast.Name) and node.args[0].func.id=='partial',(path,node.lineno)
    for node in ast.walk(ast.parse((ROOT/'screens/settings.py').read_text())):
        match node:
            case ast.Call(func=ast.Attribute(attr='call_after_refresh'),
                          args=[ast.Attribute(attr='dismiss'), *_]):
                raise AssertionError('A refresh callback must not await its modal removal')
