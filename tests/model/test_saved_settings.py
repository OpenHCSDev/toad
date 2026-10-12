"""Saved settings load and write back unchanged, without loading Textual or Qt; each declared kind of setting accepts its values and refuses the rest; the file holds exactly what the user has set."""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Annotated

from annotated_types import Ge, Le
import pytest

from acp.schema import ToolCall
from agent_comms.field_codec import FieldCodec
from python_introspect import AnnotatedDataclassValidationMixin
from toad.acp.status import ToolCallStatus
from toad.forms.kinds import Multiline
from toad.preferences import SETTINGS, SavedSettings
from toad.setting_choices import BothExpansion, Expansion, FailExpansion, FamilyChoices

SAVED = Path(__file__).resolve().parents[1] / "fixtures" / "saved-settings.json"


@dataclass(frozen=True)
class Kinds(AnnotatedDataclassValidationMixin):
    boolean: bool = False
    integer: Annotated[int, Ge(1)] = 2
    number: Annotated[float, Ge(1), Le(3)] = 2.0
    string: str = ""
    text: Annotated[str, Multiline()] = ""
    choice: Annotated[type[Expansion], FamilyChoices(Expansion)] = FailExpansion


KINDS = [
    ("boolean", True, "true"),
    ("integer", 3, False),
    ("number", 3, "3"),
    ("string", "text", 1),
    ("text", "text\nmore", []),
    ("choice", "both", "sometimes"),
]


def test_saved_settings_and_an_unknown_theme_load_without_textual_or_qt():
    subprocess.run(
        [sys.executable, "-c",
         "import json,sys; from toad.preferences import SETTINGS, SavedSettings; "
         "raw=json.load(open(sys.argv[1])); "
         "settings=SavedSettings(raw); assert settings.document()==raw; "
         "settings.set(SETTINGS.ui.theme, 'frontend-not-installed-theme'); "
         "assert settings.document()['ui']['theme']=='frontend-not-installed-theme'; "
         "loaded={name.partition('.')[0] for name in sys.modules}; "
         "assert not loaded & {'textual', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'}, loaded", str(SAVED)],
        check=True, capture_output=True, text=True, timeout=30,
    )


def test_saved_settings_write_back_unchanged():
    raw = json.loads(SAVED.read_bytes())
    current = SavedSettings(raw)
    assert current.document() == raw
    assert not current.unsaved


def test_the_file_holds_what_the_user_has_set_even_a_value_equal_to_its_default():
    current = SavedSettings({})
    assert current.document() == {} and not current.unsaved
    current.set(SETTINGS.ui.column_width, 120)
    current.set(SETTINGS.ui.column_width, 100)
    assert current.current.ui.column_width == 100
    assert current.document() == {"ui": {"column-width": 100}} and current.unsaved
    current.discard()
    assert current.document() == {} and not current.unsaved


def test_a_group_the_file_holds_empty_is_written_back_empty():
    assert SavedSettings({"diff": {}}).document() == {"diff": {}}


def test_a_key_that_is_not_a_setting_is_refused():
    with pytest.raises(ValueError):
        SavedSettings({"ui": {"no-such-setting": 1}})


def test_failed_tool_calls_expand_by_default_and_both_expansion_adds_completed_ones():
    def status(name):
        return ToolCallStatus.from_acp(ToolCall(tool_call_id=f"private-{name}", title=f"Private {name} tool", status=name))

    failed, completed, pending = status("failed"), status("completed"), status("pending")
    current = SavedSettings(json.loads(SAVED.read_bytes())).current
    assert current.tools.expand.should_expand(failed)
    assert BothExpansion.should_expand(completed) and BothExpansion.should_expand(failed)
    assert not BothExpansion.should_expand(pending)


@pytest.mark.parametrize("name, valid, invalid", KINDS, ids=[kind[0] for kind in KINDS])
def test_each_kind_of_setting_reads_its_value_and_refuses_other_input(name, valid, invalid):
    assert getattr(FieldCodec.decode(Kinds, {name: valid}), name) is not None
    with pytest.raises((ValueError, TypeError)):
        FieldCodec.decode(Kinds, {name: invalid})


def test_numeric_bounds_are_enforced_when_read_and_when_set():
    with pytest.raises(ValueError):
        FieldCodec.decode(Kinds, {"integer": 0})
    with pytest.raises(ValueError):
        FieldCodec.decode(Kinds, {"number": 4.0})
    with pytest.raises(ValueError):
        SavedSettings({"ui": {"column-width": 4}})
    current = SavedSettings({})
    with pytest.raises(ValueError):
        current.set(SETTINGS.ui.column_width, 4)
    assert current.current.ui.column_width == 100 and not current.unsaved


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True], ids=["nan", "inf", "bool"])
def test_a_number_setting_refuses_values_that_are_not_json_numbers(value):
    assert FieldCodec.decode(Kinds, {"number": 2}).number == 2.0
    with pytest.raises(ValueError):
        FieldCodec.decode(Kinds, {"number": value})
