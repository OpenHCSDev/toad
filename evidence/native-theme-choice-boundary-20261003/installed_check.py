"""Final installed checks of the changed shared/native preference boundary."""

import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import sys

from agent_comms.field_codec import FieldCodec
from toad.render_choices import LocalRenderer, RendererChoice
from toad.setting_choices import Choice
from toad.settings import ChoiceSetting
from toad.widgets.presentation_window import PresentationBudget


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    assert not any(name == "textual" or name.startswith("textual.") for name in sys.modules)
    assert "toad.native_themes" not in sys.modules
    assert FieldCodec.decode(type[RendererChoice], "local") is LocalRenderer
    assert PresentationBudget().runway_rows(24) == 72
    renderer = LocalRenderer.start()
    await renderer.aclose()
    assert not any(name == "textual" or name.startswith("textual.") for name in sys.modules)
    print("shared Choice/settings/budget/local renderer: no native toolkit import", flush=True)

    from textual.theme import BUILTIN_THEMES
    from toad.app import ToadApp
    from toad.native_themes import ThemeChoice
    from toad.preferences import ToadSettings, UiSettings
    from toad.screens.settings import SettingsScreen
    from toad.setting_widgets import ChoiceEditor

    assert set(ThemeChoice.names()) == set(BUILTIN_THEMES)
    for member in ThemeChoice.members_with(ThemeChoice):
        assert member.theme is BUILTIN_THEMES[member.declared_name]
        assert FieldCodec.decode(type[ThemeChoice], FieldCodec.encode(member)) is member
    raw = {"ui": {"theme": "ansi-dark"}}
    assert ToadSettings(raw).document() == raw
    app = ToadApp(project_dir=os.environ["TOAD_TEST_PROJECT"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("f2")
        await until(lambda: isinstance(app.screen, SettingsScreen) and any(
            editor.bound.kind is UiSettings.theme for editor in app.screen.query(ChoiceEditor)
        ))
        editor = next(editor for editor in app.screen.query(ChoiceEditor)
                      if editor.bound.kind is UiSettings.theme)
        editor.focus()
        target = ThemeChoice.decode("ansi-light")
        index = ThemeChoice.names().index(target.declared_name)
        await pilot.press("enter", "home", *("down",) * index, "enter")
        await until(lambda: app.settings.ui.theme is target and app.theme == "ansi-light")
        assert app.settings.document()["ui"]["theme"] == "ansi-light"
        await pilot.press("escape")
        await until(lambda: not isinstance(app.screen, SettingsScreen))
        settings_file = Path(os.environ["XDG_CONFIG_HOME"]) / "toad" / "toad.json"
        await until(lambda: settings_file.exists() and
                    json.loads(settings_file.read_text()).get("ui", {}).get("theme") == "ansi-light")
        assert app._exception is None
    assert not multiprocessing.active_children()
    print(json.dumps({"result": "passed", "native_theme_members": len(ThemeChoice.names()),
                      "actual_app_route": "F2 → ChoiceEditor keyboard selection → native theme effect → Escape → saved preference",
                      "theme": "ansi-light", "cleanup": []}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
