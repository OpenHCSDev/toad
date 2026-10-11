"""Textual-facing: the settings screen builds one editor widget per declared setting, applies edits at once, refuses bad input on blur, and saves to the file Toad reads back."""

from contextlib import asynccontextmanager
from dataclasses import replace
from functools import partial
import json
from pathlib import Path
import hashlib

from ui_theme.catalog import SCHEMES
from ui_theme.colour import Rgb
from ui_theme.scheme import PrimaryColour

from toad.preferences import ToadSettings, UiSettings
from toad.screens.settings import SettingsScreen
from toad.setting_widgets import BooleanEditor, ChoiceEditor, InputEditor
from toad.settings import Group, SettingsGroup, StringSetting

SAVED = Path(__file__).resolve().parents[1] / "fixtures" / "saved-settings.json"


class UppercaseSetting(StringSetting):
    def parse(self, raw: object) -> str:
        return super().parse(raw).upper()


class ExtraPreferences(SettingsGroup):
    badge = UppercaseSetting(
        title="Badge",
        default="HELLO",
        effect=lambda app, value: setattr(app, "sub_title", value),
    )


class ExtendedSettings(ToadSettings):
    experiment = Group(ExtraPreferences, title="Experiment")


@asynccontextmanager
async def settings_screen(workspace):
    """The application with the saved preferences in its config directory and the settings screen on top."""
    config = workspace.roots.attempt / "config" / "toad"
    config.mkdir(parents=True)
    (config / "toad.json").write_bytes(SAVED.read_bytes())
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        # A custom scheme is registered with the colours owner, which offers it
        # in the theme setting and registers it with Textual.
        base = SCHEMES[0]
        app.colours.register(replace(base, name="settings-private-custom",
                                     colours={**base.colours, PrimaryColour: Rgb.parse("#44aa88")}))
        await app.push_screen(SettingsScreen())
        expected = len([bound for node in ToadSettings.nodes() if node.editable for bound in node.leaves(app.settings)])
        await ui.until(lambda: len(app.screen.query(".setting")) == expected, seconds=5, why="an editor per setting")
        yield ui, app, config / "toad.json"


def editor(app, kind, kind_of_editor):
    return next(w for w in app.screen.query(kind_of_editor) if w.bound.kind is kind)


async def edit_text(ui, widget, value):
    widget.value = value
    widget.focus()
    await ui.step()
    await ui.press("tab")


async def test_opening_the_editors_changes_no_preference(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        assert app.settings.document() == json.loads(SAVED.read_bytes())
        assert not app.settings.changed, "Editor initialization changed preferences"


async def test_every_setting_kind_has_an_editor_widget(workspace):
    from toad.settings import (
        BooleanSetting, ChoiceSetting, IntegerSetting, NumberSetting, PathSetting, TextSetting,
    )
    from toad.setting_choices import Expansion, FailExpansion

    kinds = type("Kinds", (SettingsGroup,), {f"kind_{index}": kind for index, kind in enumerate((
        BooleanSetting(title="b", default=False),
        IntegerSetting(title="i", default=2, minimum=1),
        NumberSetting(title="n", default=2.0, minimum=1),
        StringSetting(title="s", default=""),
        TextSetting(title="t", default=""),
        PathSetting(title="p", default=Path(".")),
        ChoiceSetting(Expansion, title="c", default=FailExpansion),
    ))})()
    async with settings_screen(workspace) as (ui, app, _file):
        for node in kinds.nodes():
            assert app.screen.dispatch_sync(node, kinds, "") is not None


async def test_a_boolean_and_a_theme_take_effect_when_edited(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        footer = editor(app, UiSettings.footer, BooleanEditor)
        before = app.settings.ui.footer
        footer.value = not before
        await ui.step()
        assert app.settings.ui.footer is not before
        assert app.has_class("-hide-footer") is before
        theme = editor(app, UiSettings.theme, ChoiceEditor)
        theme.value = "ansi-light"
        await ui.step()
        assert app.theme == "ansi-light"
        assert app.settings.document()["ui"]["theme"] == "ansi-light"
        theme.value = "settings-private-custom"
        await ui.step()
        assert app.theme == "settings-private-custom"
        assert app.settings.document()["ui"]["theme"] == "settings-private-custom"


async def test_a_number_applies_when_focus_leaves_and_a_refused_number_is_restored(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        width = editor(app, UiSettings.column_width, InputEditor)
        await edit_text(ui, width, "120")
        assert app.settings.ui.column_width == 120
        await edit_text(ui, width, "4")
        assert app.settings.ui.column_width == 120 and width.value == "120"


async def test_a_newly_declared_setting_is_edited_applied_saved_and_read_back(workspace):
    source_before = hashlib.sha256(SAVED.read_bytes()).digest()
    async with settings_screen(workspace) as (ui, app, settings_file):
        editor(app, UiSettings.theme, ChoiceEditor).value = "settings-private-custom"
        await ui.step()
        await edit_text(ui, editor(app, UiSettings.column_width, InputEditor), "120")
        app.settings = ExtendedSettings(app.settings.document(), notify=partial(ToadSettings.apply_change, app))
        await app.pop_screen()
        await app.push_screen(SettingsScreen())
        await ui.until(lambda: any(w.bound.kind is ExtraPreferences.badge for w in app.screen.query(InputEditor)),
                       why="the new setting's editor")
        badge = editor(app, ExtraPreferences.badge, InputEditor)
        await edit_text(ui, badge, "fresh")
        assert app.settings.experiment.badge == "FRESH" and app.sub_title == "FRESH"
        await app.settings.save()
        reopened = ExtendedSettings(json.loads(settings_file.read_text()))
        assert (reopened.experiment.badge == "FRESH" and reopened.ui.column_width == 120
                and reopened.ui.theme == "settings-private-custom")
        assert not reopened.changed
    assert hashlib.sha256(SAVED.read_bytes()).digest() == source_before
