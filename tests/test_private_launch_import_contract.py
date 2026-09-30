"""Every Toad consumer must import the paired Core launch owner's public API."""
import ast
from pathlib import Path
import unittest

from agent_comms import private_nk_entrypoint


class PrivateLaunchImportContract(unittest.TestCase):
    def test_all_launch_consumers_use_available_owner_exports(self):
        source = Path(__file__).resolve().parents[1] / 'src' / 'toad'
        consumers = []
        for path in source.rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
                if isinstance(node, ast.ImportFrom) and node.module == private_nk_entrypoint.__name__:
                    consumers.append(path)
                    for binding in node.names:
                        with self.subTest(path=path.relative_to(source), name=binding.name):
                            getattr(private_nk_entrypoint, binding.name)
        self.assertTrue(consumers, 'No Core private launch consumers were checked')


if __name__ == '__main__':
    unittest.main()
