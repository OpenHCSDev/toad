"""Supported CLI selection and optional-backend isolation, without agent traffic."""

import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from toad.cli import main
from toad.render_choices import LocalRenderer, PersistentRenderer
from toad.render_processes import RenderProcessPool
from toad.render_runtime import PersistentRenderClient
class SelectionTests(unittest.TestCase):
    def test_factories_are_lazy_and_nominal(self) -> None:
        local = LocalRenderer.start()
        persistent = PersistentRenderer.start( directory=Path("/unused-renderer-selection"))
        self.assertIsInstance(local, RenderProcessPool)
        self.assertIsInstance(persistent, PersistentRenderClient)
        self.assertIsNone(persistent.resolved_pool)
        asyncio.run(local.aclose())
        asyncio.run(persistent.aclose())

    def test_missing_optional_backend_leaves_default_available(self) -> None:
        with patch("toad.render_choices.find_spec", return_value=None):
            local = LocalRenderer.start()
            asyncio.run(local.aclose())
            with self.assertRaisesRegex(RuntimeError, "persistent-renderer"):
                PersistentRenderer.start()

    def test_invalid_backend_and_missing_extra_are_actionable_cli_errors(self) -> None:
        runner = CliRunner()
        with patch("toad.cli.ToadApp") as app:
            result = runner.invoke(main, ["run", "--renderer", "invalid", "."])
            self.assertEqual(result.exit_code, 2)
            app.assert_not_called()
        with patch("toad.render_choices.PersistentRenderer.start", side_effect=RuntimeError("Install persistent-renderer extra")):
            result = runner.invoke(main, ["run", "--renderer", "persistent", "."])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("Install persistent-renderer extra", result.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
