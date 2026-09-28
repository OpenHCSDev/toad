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


def test_new_script_is_collected_once(tmp_path):
    """New script names and explicit unittest selectors run the entry point once."""
    import os
    import subprocess
    import sys

    (tmp_path / 'conftest.py').write_text((ROOT / 'tests/conftest.py').read_text())
    (tmp_path / 'pytest.ini').write_text('[pytest]\npython_files = *.py\n')
    script = tmp_path / 'fresh_behavior_pilot.py'
    script.write_text('''import unittest
from pathlib import Path
class Behavior(unittest.TestCase):
    def test_behavior(self):
        with Path(__file__).with_suffix('.receipt').open('a') as output:
            output.write('observed\\n')
if __name__ == '__main__':
    unittest.main()
''')
    environment = {**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    environment.pop('PYTHONPATH', None)
    for selector in ([], [str(script)]):
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', *selector], cwd=tmp_path,
            env=environment, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert '1 passed' in result.stdout, result.stdout
    assert script.with_suffix('.receipt').read_text().splitlines() == ['observed'] * 2
