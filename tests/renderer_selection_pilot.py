"""Supported CLI selection and optional-backend isolation, without agent traffic."""

import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from toad.cli import main
from toad.render_backend import Renderer, RendererBackend, create_renderer
from toad.render_processes import RenderProcessPool
from toad.render_runtime import PersistentRenderer
from toad.render_tasks import RenderTask
from typing import TypeVar

ResultT = TypeVar("ResultT")


class ProbeRenderer(Renderer):
    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        raise AssertionError("CLI selection must not submit rendering work")

    async def aclose(self) -> None:
        pass


class SelectionTests(unittest.TestCase):
    def test_factories_are_lazy_and_nominal(self) -> None:
        local = create_renderer()
        persistent = create_renderer(RendererBackend.PERSISTENT, directory=Path("/unused-renderer-selection"))
        self.assertIsInstance(local, RenderProcessPool)
        self.assertIsInstance(persistent, PersistentRenderer)
        self.assertIsNone(persistent.resolved_pool)
        asyncio.run(local.aclose())
        asyncio.run(persistent.aclose())

    def test_missing_optional_backend_leaves_default_available(self) -> None:
        with patch("toad.render_backend.find_spec", return_value=None):
            local = create_renderer()
            asyncio.run(local.aclose())
            with self.assertRaisesRegex(RuntimeError, "persistent-renderer"):
                create_renderer(RendererBackend.PERSISTENT)

    def test_cli_and_environment_deliver_declared_backend_to_app(self) -> None:
        runner = CliRunner()
        for args, environment, expected in (
            (["run", "."], {}, RendererBackend.LOCAL),
            (["run", "--renderer", "persistent", "."], {}, RendererBackend.PERSISTENT),
            (["acp", "test-agent", ".", "--session", "saved"], {"TOAD_RENDERER": "persistent"}, RendererBackend.PERSISTENT),
            (["acp", "--renderer", "local", "test-agent", "."], {"TOAD_RENDERER": "persistent"}, RendererBackend.LOCAL),
        ):
            backend = ProbeRenderer()
            with (patch("toad.cli.ToadApp") as app,
                  patch("toad.cli.create_renderer", return_value=backend) as factory,
                  patch.dict("os.environ", {"TOAD_RENDERER": "local"})):
                result = runner.invoke(main, args, env=environment)
                self.assertEqual(result.exit_code, 0, result.output)
                factory.assert_called_once_with(expected)
                self.assertIs(app.call_args.kwargs["renderer"], backend)
                app.return_value.run.assert_called_once_with()

    def test_invalid_backend_and_missing_extra_are_actionable_cli_errors(self) -> None:
        runner = CliRunner()
        with patch("toad.cli.ToadApp") as app:
            result = runner.invoke(main, ["run", "--renderer", "invalid", "."])
            self.assertEqual(result.exit_code, 2)
            app.assert_not_called()
        with patch("toad.cli.create_renderer", side_effect=RuntimeError("Install persistent-renderer extra")):
            result = runner.invoke(main, ["run", "--renderer", "persistent", "."])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("Install persistent-renderer extra", result.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
