"""Keep one installed ratchet and one derived pilot collector."""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CollectionGuards(unittest.TestCase):
    def test_no_machine_paths_or_skipped_behavior(self):
        for directory in ('tests', 'src'):
            for path in (ROOT/directory).rglob('*.py'):
                source=path.read_text()
                # Assemble the sentinel so this guard doesn't contain its own
                # forbidden machine-specific path literal.
                self.assertNotIn('/'+'home/', source, str(path))
                tree=ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                        for decorator in node.decorator_list:
                            name=ast.unparse(decorator)
                            self.assertNotIn('pytest.mark.skip',name,str(path))
                            self.assertNotIn('pytest.mark.xfail',name,str(path))

    def test_manual_roster_and_copy_are_gone(self):
        document=(ROOT/'tests/THREAD_WORKFLOWS.md').read_text()
        self.assertNotIn('python tests/', document)
        self.assertNotIn('install -e', document)
        self.assertFalse((ROOT/'tools/debt_ratchet.py').exists())
        collector=(ROOT/'tests/conftest.py').read_text()
        self.assertNotIn('PILOTS =', collector)
        self.assertNotIn('PYTHONPATH=src', collector)
