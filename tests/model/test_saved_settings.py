"""Saved preferences load and write back unchanged, without loading Textual; every setting kind accepts its input and refuses the rest."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from acp.schema import ToolCall
from toad.acp.status import ToolCallStatus
from toad.preferences import ToadSettings
from toad.setting_choices import BothExpansion, Expansion, FailExpansion
from toad.settings import (
    BooleanSetting, ChoiceSetting, IntegerSetting, NumberSetting, PathSetting, StringSetting, TextSetting,
)

SAVED = Path(__file__).resolve().parents[1] / "fixtures" / "saved-settings.json"

KINDS = [
    (BooleanSetting(title="b", default=False), True, "true"),
    (IntegerSetting(title="i", default=2, minimum=1), 3, False),
    (NumberSetting(title="n", default=2.0, minimum=1), 3.0, "3"),
    (StringSetting(title="s", default=""), "text", 1),
    (TextSetting(title="t", default=""), "text\nmore", []),
    (PathSetting(title="p", default=Path(".")), "$HOME/file", 2),
    (ChoiceSetting(Expansion, title="c", default=FailExpansion), "both", "sometimes"),
]


def test_saved_preferences_and_an_unknown_theme_load_without_textual():
    subprocess.run(
        [sys.executable, "-c",
         "import json,sys; from toad.preferences import ToadSettings; "
         "raw=json.load(open(sys.argv[1])); "
         "settings=ToadSettings(raw); assert settings.document()==raw; "
         "settings.ui.theme='frontend-not-installed-theme'; "
         "assert settings.document()['ui']['theme']=='frontend-not-installed-theme'; "
         "assert not any(name=='textual' or name.startswith('textual.') for name in sys.modules)", str(SAVED)],
        check=True, capture_output=True, text=True, timeout=30,
    )


def test_saved_preferences_write_back_unchanged():
    raw = json.loads(SAVED.read_bytes())
    current = ToadSettings(raw)
    assert current.document() == raw
    assert not current.changed


def test_failed_tool_calls_expand_by_default_and_both_expansion_adds_completed_ones():
    def status(name):
        return ToolCallStatus.from_acp(ToolCall(tool_call_id=f"private-{name}", title=f"Private {name} tool", status=name))

    failed, completed, pending = status("failed"), status("completed"), status("pending")
    current = ToadSettings(json.loads(SAVED.read_bytes()))
    assert current.tools.expand.should_expand(failed)
    assert BothExpansion.should_expand(completed) and BothExpansion.should_expand(failed)
    assert not BothExpansion.should_expand(pending)


@pytest.mark.parametrize("kind, valid, invalid", KINDS, ids=lambda value: type(value).__name__)
def test_each_setting_kind_accepts_its_input_and_refuses_other_input(kind, valid, invalid):
    assert kind.parse(valid) is not None
    with pytest.raises((ValueError, TypeError)):
        kind.parse(invalid)


def test_numeric_bounds_are_enforced():
    with pytest.raises(ValueError):
        IntegerSetting(title="i", default=2, minimum=1).parse(0)
    with pytest.raises(ValueError):
        NumberSetting(title="n", default=2.0, maximum=3).parse(4.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True], ids=["nan", "inf", "bool"])
def test_a_number_setting_refuses_values_that_are_not_json_numbers(value):
    number = NumberSetting(title="number", default=1.0)
    assert number.parse(2) == 2.0
    with pytest.raises(ValueError):
        number.parse(value)
