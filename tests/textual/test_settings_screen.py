"""Textual-facing: the settings screen shows one editor per declared setting, applies edits at once, refuses bad input on blur, marks what differs from the file, and saves to the file Toad reads back."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Annotated

from python_introspect import AnnotatedDataclassValidationMixin, FieldLabel
from ui_theme.catalog import SCHEMES
from ui_theme.colour import Rgb
from ui_theme.scheme import PrimaryColour

from toad.forms import editors
from toad.forms.field_path import FieldPath, leaves
from toad.forms.form_view import ValueView
from toad.preferences import SETTINGS, SavedSettings, ToadSettings
from toad.screens.settings import SchemeEditor, SettingsScreen
from toad.setting_effects import Effect

SAVED = Path(__file__).resolve().parents[1] / "fixtures" / "saved-settings.json"


@dataclass(frozen=True)
class Shouted:
    """Declares text that is kept in capitals."""


class ShoutedEditor(editors.StrEditor):
    shows = (Shouted,)

    def read(self, text: str) -> object:
        return text.upper()


@Effect
def badge_shown(app, value):
    app.sub_title = value


@dataclass(frozen=True)
class ExperimentSettings(AnnotatedDataclassValidationMixin):
    badge: Annotated[str, FieldLabel("Badge"), Shouted(), badge_shown] = "HELLO"
    """Shown beside the title."""


@dataclass(frozen=True)
class ExtendedSettings(ToadSettings):
    experiment: Annotated[ExperimentSettings, FieldLabel("Experiment")] = field(default_factory=ExperimentSettings)


EXTENDED = FieldPath(ExtendedSettings)


async def form_shown(ui, app):
    await ui.until(lambda: all(view.is_mounted for view in app.screen.form.values.values()),
                   seconds=5, why="an editor per setting")


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
        await form_shown(ui, app)
        yield ui, app, config / "toad.json"


def editor(app, path):
    return app.screen.form.values[path.bind(app.saved_settings.state)].editor


def marked(app, path):
    return ValueView.CHANGED_MARK in str(app.screen.form.values[path.bind(app.saved_settings.state)].title.render())


async def edit_text(ui, widget, value):
    widget.value = value
    widget.focus()
    await ui.step()
    await ui.press("tab")


async def test_opening_the_editors_changes_no_preference(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        assert app.saved_settings.document() == json.loads(SAVED.read_bytes())
        assert not app.saved_settings.unsaved, "Opening the form changed preferences"


async def test_every_setting_the_user_may_edit_has_an_editor(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        shown = app.screen.form.values
        state = app.saved_settings.state
        hidden = {SETTINGS.anon_id.bind(state)} | {path.bind(state) for path in leaves(SETTINGS.launcher)}
        assert set(shown) == {path.bind(state) for path in leaves(SETTINGS)} - hidden
        assert isinstance(editor(app, SETTINGS.ui.footer), editors.BoolEditor)
        assert isinstance(editor(app, SETTINGS.ui.column_width), editors.IntEditor)
        assert isinstance(editor(app, SETTINGS.ui.theme), SchemeEditor)
        assert isinstance(editor(app, SETTINGS.tools.expand), editors.ChoicesEditor)


async def test_a_boolean_and_a_theme_take_effect_when_edited(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        footer = editor(app, SETTINGS.ui.footer)
        before = app.settings.ui.footer
        footer.value = not before
        await ui.step()
        assert app.settings.ui.footer is not before
        assert app.has_class("-hide-footer") is before
        theme = editor(app, SETTINGS.ui.theme)
        theme.value = "ansi-light"
        await ui.step()
        assert app.theme == "ansi-light"
        assert app.saved_settings.document()["ui"]["theme"] == "ansi-light"
        theme.value = "settings-private-custom"
        await ui.step()
        assert app.theme == "settings-private-custom"
        assert app.saved_settings.document()["ui"]["theme"] == "settings-private-custom"


async def test_a_number_applies_when_focus_leaves_and_a_refused_number_is_restored(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        width = editor(app, SETTINGS.ui.column_width)
        await edit_text(ui, width, "120")
        assert app.settings.ui.column_width == 120
        await edit_text(ui, width, "4")
        assert app.settings.ui.column_width == 120 and width.value == "120"


async def test_a_changed_setting_is_marked_and_discarding_puts_the_file_back(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        saved = app.settings
        await edit_text(ui, editor(app, SETTINGS.ui.column_width), "120")
        editor(app, SETTINGS.ui.footer).value = not saved.ui.footer
        await ui.step()
        assert marked(app, SETTINGS.ui.column_width) and marked(app, SETTINGS.ui.footer)
        assert not marked(app, SETTINGS.ui.theme)
        await ui.press("ctrl+r")
        await ui.until(lambda: not marked(app, SETTINGS.ui.column_width), why="the discard")
        assert not marked(app, SETTINGS.ui.footer)
        assert app.settings == saved and not app.saved_settings.unsaved
        assert editor(app, SETTINGS.ui.column_width).value == str(saved.ui.column_width)
        assert editor(app, SETTINGS.ui.footer).value is saved.ui.footer
        assert app.has_class("-hide-footer") is not saved.ui.footer


async def test_closing_the_form_sends_the_number_still_being_typed(workspace):
    async with settings_screen(workspace) as (ui, app, _file):
        width = editor(app, SETTINGS.ui.column_width)
        width.focus()
        width.value = "130"
        await ui.step()
        await ui.press("escape")
        await ui.until(lambda: not isinstance(app.screen, SettingsScreen), why="the form to close")
        assert app.settings.ui.column_width == 130


async def test_a_newly_declared_setting_is_edited_applied_saved_and_read_back(workspace):
    source_before = hashlib.sha256(SAVED.read_bytes()).digest()
    async with settings_screen(workspace) as (ui, app, settings_file):
        editor(app, SETTINGS.ui.theme).value = "settings-private-custom"
        await ui.step()
        await edit_text(ui, editor(app, SETTINGS.ui.column_width), "120")
        await app.pop_screen()
        app.saved_settings = SavedSettings(
            app.saved_settings.document(), root=ExtendedSettings, applied=app.saved_settings.applied
        )
        await app.push_screen(SettingsScreen())
        await form_shown(ui, app)
        badge = editor(app, EXTENDED.experiment.badge)
        assert isinstance(badge, ShoutedEditor)
        await edit_text(ui, badge, "fresh")
        assert app.settings.experiment.badge == "FRESH" and app.sub_title == "FRESH"
        await app.saved_settings.save()
        reopened = SavedSettings(json.loads(settings_file.read_text()), root=ExtendedSettings)
        assert (reopened.current.experiment.badge == "FRESH" and reopened.current.ui.column_width == 120
                and reopened.current.ui.theme == "settings-private-custom")
        assert not reopened.unsaved
    assert hashlib.sha256(SAVED.read_bytes()).digest() == source_before
