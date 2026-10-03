"""T1: real saved preferences, declaration extension and mounted editing."""

from __future__ import annotations

import asyncio
from functools import partial
import hashlib
import json
import os
from pathlib import Path
from importlib.resources import files
from tempfile import TemporaryDirectory
from unittest.mock import patch

from toad.app import ToadApp
from toad.acp.status import ToolCallStatus
from acp.schema import ToolCall
from toad.preferences import ToadSettings, UiSettings
from toad.screens.settings import SettingsScreen
from toad.setting_choices import BothExpansion, Expansion, FailExpansion
from toad.native_themes import ThemeChoice
from toad.setting_widgets import BooleanEditor, ChoiceEditor, InputEditor
from toad.settings import (
    BooleanSetting,
    ChoiceSetting,
    Group,
    IntegerSetting,
    NumberSetting,
    PathSetting,
    SettingsGroup,
    StringSetting,
    TextSetting,
)


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


class SettingsApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    def _handle_exception(self, error: Exception) -> None:
        import traceback

        traceback.print_exception(error)
        super()._handle_exception(error)

    async def on_mount(self, event) -> None:
        event.prevent_default()
        await self.push_screen(SettingsScreen())


async def main() -> None:
    source = Path(os.environ.get("TOAD_SETTINGS_SAMPLE", str(Path(__file__).with_name("fixtures") / "saved-settings.json")))
    original = source.read_bytes()
    raw = json.loads(original)
    current = ToadSettings(raw)
    assert current.document() == raw
    assert not current.changed
    failed = ToolCallStatus.from_acp(ToolCall(tool_call_id="private-failed", status="failed"))
    completed = ToolCallStatus.from_acp(ToolCall(tool_call_id="private-completed", status="completed"))
    pending = ToolCallStatus.from_acp(ToolCall(tool_call_id="private-pending", status="pending"))
    assert current.tools.expand.should_expand(failed)
    assert BothExpansion.should_expand(completed) and BothExpansion.should_expand(failed)
    assert not BothExpansion.should_expand(pending)
    fixtures = [
        (BooleanSetting(title="b", default=False), True, "true"),
        (IntegerSetting(title="i", default=2, minimum=1), 3, False),
        (NumberSetting(title="n", default=2.0, minimum=1), 3.0, "3"),
        (StringSetting(title="s", default=""), "text", 1),
        (TextSetting(title="t", default=""), "text\nmore", []),
        (PathSetting(title="p", default=Path(".")), "$HOME/file", 2),
        (
            ChoiceSetting(Expansion, title="c", default=FailExpansion),
            "both",
            "sometimes",
        ),
    ]
    for kind, valid, invalid in fixtures:
        assert kind.parse(valid) is not None
        try:
            kind.parse(invalid)
        except ValueError, TypeError:
            pass
        else:
            raise AssertionError(f"{type(kind).__name__} accepted invalid input")
    kinds = type(
        "Kinds",
        (SettingsGroup,),
        {f"kind_{index}": kind for index, (kind, _, _) in enumerate(fixtures)},
    )()
    for kind in (
        IntegerSetting(title="i", default=2, minimum=1),
        NumberSetting(title="n", default=2.0, maximum=3),
    ):
        try:
            kind.parse(0 if kind.minimum is not None else 4.0)
        except ValueError:
            pass
        else:
            raise AssertionError("Bounds not enforced")
    number = NumberSetting(title="number", default=1.0)
    assert number.parse(2) == 2.0
    for value in (float("nan"), float("inf"), True):
        try:
            number.parse(value)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid JSON number accepted")
    root_parent = Path(__file__).resolve().parents[1] / ".artifacts"
    root_parent.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=root_parent, prefix="settings-") as temporary:
        root = Path(temporary)
        config = root / "config" / "toad"
        config.mkdir(parents=True)
        settings_file = config / "toad.json"
        settings_file.write_bytes(original)
        with patch.dict(
            os.environ,
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        ):
            app = SettingsApp()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                for node in kinds.nodes():
                    assert app.screen.dispatch_sync(node, kinds, "") is not None
                assert app.settings.document() == raw
                expected = len(
                    [
                        bound
                        for node in ToadSettings.nodes()
                        if node.editable
                        for bound in node.leaves(app.settings)
                    ]
                )
                async with asyncio.timeout(5):
                    while len(app.screen.query(".setting")) != expected:
                        await pilot.pause(0.05)
                if evidence_path := os.environ.get("TOAD_SETTINGS_EVIDENCE"):
                    evidence = Path(evidence_path)
                    evidence.mkdir(parents=True, exist_ok=True)
                    app.save_screenshot(str(evidence / "settings-initial.svg"))
                assert not app.settings.changed, (
                    "Editor initialization changed preferences"
                )
                footer = next(
                    w
                    for w in app.screen.query(BooleanEditor)
                    if w.bound.kind is UiSettings.footer
                )
                before = app.settings.ui.footer
                footer.value = not before
                await pilot.pause()
                assert app.settings.ui.footer is not before
                assert app.has_class("-hide-footer") is before
                theme = next(
                    w
                    for w in app.screen.query(ChoiceEditor)
                    if w.bound.kind is UiSettings.theme
                )
                theme.value = ThemeChoice.decode("ansi-light")
                await pilot.pause()
                assert app.theme == "ansi-light"
                assert app.settings.document()["ui"]["theme"] == "ansi-light"
                width = next(
                    w
                    for w in app.screen.query(InputEditor)
                    if w.bound.kind is UiSettings.column_width
                )
                width.value = "120"
                width.focus()
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                assert app.column_width == 120
                width.value = "4"
                width.focus()
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                assert app.column_width == 120 and width.value == "120"
                app.settings = ExtendedSettings(
                    app.settings.document(), notify=partial(ToadSettings.apply_change, app)
                )
                await app.pop_screen()
                await app.push_screen(SettingsScreen())
                await pilot.pause()
                badge = next(
                    w
                    for w in app.screen.query(InputEditor)
                    if w.bound.kind is ExtraPreferences.badge
                )
                badge.value = "fresh"
                badge.focus()
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                assert (
                    app.settings.experiment.badge == "FRESH"
                    and app.sub_title == "FRESH"
                )
                await app.settings.save()
                reopened = ExtendedSettings(json.loads(settings_file.read_text()))
                assert (
                    reopened.experiment.badge == "FRESH"
                    and reopened.ui.column_width == 120
                )
                assert not reopened.changed
                if evidence_path := os.environ.get("TOAD_SETTINGS_EVIDENCE"):
                    evidence = Path(evidence_path)
                    app.save_screenshot(str(evidence / "settings-subtype-edited.svg"))
                    (evidence / "receipt.json").write_text(json.dumps({
                        "result": "pass-installed-settings-app",
                        "installed_toad": __import__("toad").__file__,
                        "source_settings": str(source),
                        "source_sha256": hashlib.sha256(original).hexdigest(),
                        "original_document_roundtrip": True,
                        "all_original_field_kinds_and_bounds": True,
                        "model_values_unchanged_on_form_initialization": True,
                        "boolean_theme_native_effects": True,
                        "numeric_focus_blur_success_and_refusal": True,
                        "inherited_uppercase_descriptor_native_editor": True,
                        "save_reopen_same_original_values": True,
                        "providers": 0, "native_pi_inputs": 0,
                        "scope": "Installed original App/Pilot/settings/edit/effects/save/reopen, not physical st/ACP/Pi/performance",
                    }, indent=2) + "\n")
    assert (
        hashlib.sha256(source.read_bytes()).digest()
        == hashlib.sha256(original).digest()
    )
    print(
        "PASS real saved settings unchanged; all kinds/bounds; mounted editing/effects; new declaration; save/reopen; original untouched"
    )


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 45))
