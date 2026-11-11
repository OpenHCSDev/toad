"""The settings picker supplies the workspace's native hint caption behavior."""
import json

from textual.widgets import Static
from textual.widgets._hints import HintSession

from toad.hint_labels import HintLabels
from toad.preferences import SETTINGS, SavedSettings
from toad.screens.settings import SettingsScreen
from toad.setting_declarations import FamilyChoices


async def test_hint_picker_saves_and_drives_both_native_presentations(workspace):
    async with workspace.app(size=(140, 42), notifications=True) as ui:
        app, pilot = ui.textual
        body = Static("\n".join(
            f"[@click=app.notify('Hint choice activated {index}')]Target {index}[/]"
            for index in range(27)))
        body.styles.position = "absolute"
        body.styles.offset = (60, 4)
        body.styles.width = 35
        body.styles.height = 27
        body.styles.layer = "_tooltips"
        await app.screen.mount(body)
        draft = "Local hint probe; never submitted"
        await ui.write_draft(draft)
        for choice in FamilyChoices(HintLabels).choices():
            await app.push_screen(SettingsScreen())
            await ui.until(lambda: str(SETTINGS.ui.hint_labels) in app.screen.values,
                           why="the Hint labels picker")
            picker = app.screen.values[str(SETTINGS.ui.hint_labels)].editor
            picker.value = choice
            await ui.step()
            await app.pop_screen()
            assert app.screen.hint_label_style is choice
            await app.screen.action_show_hints()
            await ui.step()
            session = app.screen.query_one(HintSession)
            assert session.label_style is choice
            label = next(label for label in session.labels if label.target.widget is body)
            assert len(label.text) == 2
            assert label.render().plain == choice.caption(label.text, "")
            await pilot.press(*label.text)
            await ui.until_shows("Hint choice activated")
            assert ui.draft() == draft
            await app.saved_settings.save()
            reopened = SavedSettings(json.loads(workspace.roots.settings.read_text()))
            assert reopened.current.ui.hint_labels is choice
