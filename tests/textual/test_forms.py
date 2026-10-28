"""Textual-facing: a form drawn from dataclass declarations over an ObjectState shows one editor per kind of field, sends edits to the state, marks what differs from the saved value and repaints when the state changes."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
import subprocess
import sys
from typing import Annotated, Optional

from annotated_types import Ge
from objectstate import ObjectState
from python_introspect import AnnotatedDataclassValidationMixin, AnnotationChoices, FieldLabel
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Select

import toad.preferences  # noqa: F401  names the process-wide root ObjectState asks for (ObjectState issue #44)
from toad.forms import editors
from formbridge.forms.declared_fields import FieldPath
from toad.forms.form_view import FormView, GroupView, ValueView
from formbridge.forms.declared_fields import Multiline
from toad.textual_colours import ThemedApp


class Size(Enum):
    SMALL = "small"
    LARGE = "large"


class Fruit(AnnotationChoices):
    def choices(self):
        return ("apple", "pear")

    def label(self, choice):
        return str(choice).upper()


@dataclass(frozen=True)
class Inner(AnnotatedDataclassValidationMixin):
    depth: Annotated[int, FieldLabel("How deep"), Ge(1)] = 2
    """Levels below the surface."""


@dataclass(frozen=True)
class Everything(AnnotatedDataclassValidationMixin):
    flag: bool = False
    count: Annotated[int, Ge(1)] = 3
    ratio: float = 1.5
    name: str = "plain"
    notes: Annotated[str, Multiline()] = "one\ntwo"
    size: Size = Size.SMALL
    fruit: Annotated[str, Fruit()] = "apple"
    limit: Optional[Annotated[int, Ge(1)]] = None
    inner: Inner = field(default_factory=Inner)
    secret: str = field(default="", metadata={"ui_hidden": True})


class FormApp(ThemedApp, App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.state = ObjectState(Everything())

    def compose(self) -> ComposeResult:
        self.form = FormView.whole(self.state)
        yield self.form


@asynccontextmanager
async def open_form():
    app = FormApp()
    async with app.run_test(size=(80, 60)) as pilot:
        for _ in range(100):
            if all(view.is_mounted for view in app.form.values.values()):
                break
            await pilot.pause(0.02)
        yield app, pilot, {path: view.editor for path, view in app.form.values.items()}


async def leave(pilot, editor, text):
    editor.focus()
    editor.value = text
    await pilot.pause()
    await pilot.press("tab")
    await pilot.pause()


async def test_each_kind_of_field_gets_the_editor_registered_for_its_declaration():
    async with open_form() as (app, _pilot, shown):
        assert {path: type(editor) for path, editor in shown.items()} == {
            "flag": editors.BoolEditor,
            "count": editors.IntEditor,
            "ratio": editors.FloatEditor,
            "name": editors.StrEditor,
            "notes": editors.MultilineEditor,
            "size": editors.EnumEditor,
            "fruit": editors.ChoicesEditor,
            "limit": editors.OptionalEditor,
            "inner.depth": editors.IntEditor,
        }
        assert isinstance(shown["limit"].member, editors.IntEditor)
        group = app.form.parts[-1]
        assert isinstance(group, GroupView) and [type(part) for part in group.parts] == [ValueView]
        assert app.form.values["inner.depth"].field.label == "How deep"
        assert "Levels below the surface." in str(app.form.values["inner.depth"].description())


async def test_an_edit_of_each_kind_reaches_the_state():
    async with open_form() as (app, pilot, shown):
        shown["flag"].value = True
        await leave(pilot, shown["count"], "7")
        await leave(pilot, shown["ratio"], "2.25")
        await leave(pilot, shown["name"], "edited")
        shown["notes"].load_text("three")
        shown["size"].value = Size.LARGE
        shown["fruit"].value = "pear"
        shown["limit"].holds_value.value = True
        await pilot.pause()
        assert shown["limit"].member.display
        await leave(pilot, shown["limit"].member, "9")
        await leave(pilot, shown["inner.depth"], "5")
        assert app.state.to_object() == Everything(
            flag=True, count=7, ratio=2.25, name="edited", notes="three", size=Size.LARGE,
            fruit="pear", limit=9, inner=Inner(depth=5),
        )
        shown["limit"].holds_value.value = False
        await pilot.pause()
        assert app.state.to_object().limit is None and not shown["limit"].member.display


async def test_a_value_the_declaration_refuses_is_reported_and_the_editor_shows_the_state_again():
    async with open_form() as (app, pilot, shown):
        await leave(pilot, shown["count"], "0")
        assert app.state.to_object().count == 3 and shown["count"].value == "3"
        assert any("at least 1" in notification.message for notification in app._notifications)
        await leave(pilot, shown["count"], "")
        assert app.state.to_object().count == 3 and shown["count"].value == "3"


async def test_a_changed_field_is_marked_until_it_is_saved_or_put_back():
    async with open_form() as (app, pilot, shown):
        title = app.form.values["count"].title
        await leave(pilot, shown["count"], "7")
        assert ValueView.CHANGED_MARK in str(title.render())
        app.state.mark_saved()
        await pilot.pause()
        assert ValueView.CHANGED_MARK not in str(title.render())
        await leave(pilot, shown["count"], "8")
        shown["flag"].value = True
        await pilot.pause()
        assert ValueView.CHANGED_MARK in str(title.render())
        app.state.restore_saved()
        await pilot.pause()
        assert ValueView.CHANGED_MARK not in str(title.render())
        assert shown["count"].value == "7" and shown["flag"].value is False


async def test_a_change_made_elsewhere_is_painted_without_being_sent_back():
    async with open_form() as (app, pilot, shown):
        sent = []
        app.state.on_resolved_changed(sent.append)
        app.state.update_parameter("size", Size.LARGE)
        app.state.update_parameter("flag", True)
        app.state.update_parameter("notes", "elsewhere")
        app.state.update_parameter("limit", 4)
        await pilot.pause()
        assert shown["size"].value is Size.LARGE and shown["flag"].value is True
        assert shown["notes"].text == "elsewhere"
        assert shown["limit"].holds_value.value is True and shown["limit"].member.value == "4"
        assert sent == [{"size"}, {"flag"}, {"notes"}, {"limit"}]


async def test_a_search_shows_only_the_fields_whose_labels_match():
    async with open_form() as (app, pilot, _shown):
        app.form.filter("DEEP")
        await pilot.pause()
        assert [path for path, view in app.form.values.items() if view.display] == ["inner.depth"]
        assert app.form.parts[-1].display
        app.form.filter("count")
        assert not app.form.parts[-1].display and app.form.values["count"].display
        app.form.filter("")
        assert all(view.display for view in app.form.values.values())


def test_the_form_package_loads_without_qt_or_the_comms_package():
    subprocess.run(
        [sys.executable, "-c",
         "import sys; import toad.forms.form_view, toad.forms.editors; "
         "loaded = {name.partition('.')[0] for name in sys.modules}; "
         "assert not loaded & {'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'agent_comms', 'zmq', 'numpy'}, loaded"],
        check=True, capture_output=True, text=True, timeout=60,
    )
