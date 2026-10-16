"""NRA source evidence for the existing forms and category-filter families."""
import ast
import json
import subprocess
import sys
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index
from nominal_refactor_advisor.class_index import build_class_family_index

roots = [Path('/home/ts/wt/toad-forms-migration/src/toad'),
         Path('/home/ts/wt/textual-native-forms/src/textual'),
         Path('/home/ts/wt/objectstate-native-forms/src/objectstate'),
         Path('/home/ts/wt/formbridge-native-forms/src/formbridge'),
         Path('/home/ts/wt/pyqt-native-formbridge/src/pyqt_reactive'),
         Path('/home/ts/wt/core-forms-migration/src/agent_comms'),
         Path('/home/ts/code/projects/openhcs/openhcs')]
terms = {'message_category', 'apply_block_filter', 'keep_live_block', 'block_category',
         'selected_categories', 'visible_categories', 'set_display_constraint',
         'update_classes', 'set_class', 'has_class', 'parameters_for_state',
         'is_optional', 'WidgetCreationConfig', 'widget_creation_type',
         'shown_in', 'FieldView', 'DeclaredField', 'FormView', 'SortDialog',
         'NewThreadCliCommand', 'ForkCliCommand', 'NewThreadSpec', 'ForkSpec',
         'CommsForkTool', 'initial_prompt', 'pi_bin', 'prompt', 'TargetField',
         'TargetAction', 'ModelConfigOption', 'ThinkingLevelConfigOption',
         'ConfigOptions', 'CommandDialog', 'NativeThreadDefaults',
         'LayoutKind', 'LayoutStrategy', 'title_components', 'is_nested',
         'unwrapped_type', 'WidgetCreationPipeline', 'WidgetCreationRuntime'}
modules, classes, sites, errors = [], [], [], []
for root in roots:
    for path in root.rglob('*.py'):
        try:
            source = path.read_text()
            qt = Path('/home/ts/wt/pyqt-native-formbridge')
            if '--qt-before' in sys.argv and path in {
                    qt / 'src/pyqt_reactive/forms/widget_creation_config.py',
                    qt / 'src/pyqt_reactive/forms/widget_creation_types.py'}:
                source = subprocess.check_output(
                    ['git', '-C', str(qt), 'show', 'HEAD:' + str(path.relative_to(qt))], text=True)
            parsed = SourceModule.from_source_path(path, source).parse()
        except Exception as error:
            errors.append((str(path), str(error)))
            continue
        modules.append(parsed)
        syntax = module_syntax_index(parsed.module)
        for _, node in syntax.indexed_nodes_of_type(ast.ClassDef):
            classes.append((str(path), node.lineno, node.name, [ast.unparse(base) for base in node.bases]))
        for _, node in syntax.indexed_nodes_of_type(ast.ImportFrom):
            if any(name.name in terms for name in node.names):
                sites.append((str(path), node.lineno, 'import', ast.unparse(node)))
        for kind in (ast.Call, ast.Attribute, ast.Name, ast.FunctionDef, ast.AnnAssign, ast.Assign):
            for _, node in syntax.indexed_nodes_of_type(kind):
                text = ast.unparse(node)
                if any(term in text for term in terms) and len(text) < 2500:
                    sites.append((str(path), node.lineno, kind.__name__, text))
index = build_class_family_index(modules)
print(json.dumps({'roots': list(map(str, roots)), 'modules': len(modules),
                  'classes': classes, 'indexed_classes': len(index.classes_by_symbol),
                  'sites': sites, 'parse_errors': errors}, indent=2))
