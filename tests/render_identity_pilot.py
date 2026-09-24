"""Persistent build identity covers editable changes without depending on mtimes."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from toad.render_identity import RenderCodePackage, RendererBuild
from toad.render_service import RenderServiceConfig


class IdentityTests(unittest.TestCase):
    def test_source_changes_additions_and_removals_invalidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "worker.py"
            source.write_text("result = 1\n")
            build = RendererBuild("interpreter", (RenderCodePackage("fixture", root),), RenderServiceConfig())
            original = build.version
            self.assertEqual(build.version, original)
            source.write_text("result = 2\n")
            self.assertNotEqual(build.version, original)
            source.write_text("result = 1\n")
            self.assertEqual(build.version, original)
            added = root / "parser.py"
            added.write_text("result = 1\n")
            self.assertNotEqual(build.version, original)
            added.unlink()
            self.assertEqual(build.version, original)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "worker.pyc").write_bytes(b"cache")
            self.assertEqual(build.version, original)

    def test_interpreter_config_and_dependency_locations_are_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            for location in (first, second):
                (location / "dependency.py").write_text("result = 1\n")
            build = RendererBuild("python-a", (RenderCodePackage("dependency", first),), RenderServiceConfig())
            original = build.version
            for changed in (
                replace(build, interpreter="python-b"),
                replace(build, config=RenderServiceConfig(max_workers=1)),
                replace(build, config=RenderServiceConfig(max_pending=8)),
                replace(build, config=RenderServiceConfig(client_lease_seconds=120)),
                replace(build, packages=(RenderCodePackage("dependency", second),)),
            ):
                self.assertNotEqual(changed.version, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
