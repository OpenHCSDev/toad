"""Unchanged CSS reparses never restyle old tabs; real CSS changes still do."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from textual.widgets import Static
from toad.widgets.agent_response import AgentResponse


class ComponentProbe(Static):
    COMPONENT_CLASSES = {"probe-label"}
    DEFAULT_CSS = "ComponentProbe .probe-label { color: #112233; }"


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-resume-style-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first_mode = app.current_mode
            first = app.screen
            await first.conversation.contents.mount(AgentResponse("Style target"))
            target = Static("Scoped selector target", id="style-target")
            component = ComponentProbe("Component target")
            await first.conversation.contents.mount(target, component)
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            await app.switch_mode(first_mode)
            await pilot.pause()
            assert first._resume_style is not None
            rules_before = id(app.stylesheet.rules_map)
            app.stylesheet.reparse()
            assert id(app.stylesheet.rules_map) != rules_before
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                styled.assert_not_called()

            app.stylesheet.add_source(
                "UnrelatedView { color: #112233; }", scope="UnrelatedView",
                read_from=("benchmark", "Unrelated.DEFAULT_CSS"), is_default_css=True,
            )
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                styled.assert_not_called()

            # Scope metadata alone is insufficient: the parser can leave an
            # earlier comma group global. Honor the parsed selector groups.
            app.stylesheet.add_source(
                "#style-target, UnrelatedView { color: #335577; }", scope="UnrelatedView",
                read_from=("benchmark", "Comma.DEFAULT_CSS"), is_default_css=True,
            )
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                assert target.styles.color.hex == "#335577"

            del app.stylesheet.source[("benchmark", "Comma.DEFAULT_CSS")]
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                assert target.styles.color.hex != "#335577"

            app.stylesheet.add_source(
                "AgentResponse { color: #ffaa22; }",
                read_from=("benchmark", "Changed.DEFAULT_CSS"), is_default_css=True,
            )
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                assert first.query_one(AgentResponse).styles.color.hex == "#FFAA22"
            assert app._exception is None

            app.stylesheet.add_source(
                "ComponentProbe .probe-label { color: #abcdef; }",
                read_from=("benchmark", "Component.DEFAULT_CSS"), is_default_css=True,
            )
            app.stylesheet.parse()
            await app.switch_mode(second)
            await app.switch_mode(first_mode)
            await pilot.pause()
            assert component.get_component_styles("probe-label").color.hex == "#ABCDEF"

            # Root-class updates already apply the full tree immediately. Their
            # completed revision must not be repeated on the next activation.
            first.add_class("revision-applied")
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                styled.assert_not_called()

            # A source reorder changes specificity tie-breaking even if every
            # declaration remains identical. Preserve the full refresh fallback.
            key = ("benchmark", "Changed.DEFAULT_CSS")
            value = app.stylesheet.source.pop(key)
            app.stylesheet.source[key] = value
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                assert styled.call_count > 0
        await asyncio.get_running_loop().shutdown_default_executor()
    print("resume styles: unrelated parsed type scopes skip restyle; matching/removed/comma sources refresh")


if __name__ == "__main__":
    asyncio.run(main())
