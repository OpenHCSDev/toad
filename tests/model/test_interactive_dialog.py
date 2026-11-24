"""Unified interactive dialog parsing, validation, Qt widget, and Textual widget tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from acp import schema
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton, QWidget
from textual.app import App, ComposeResult

from toad.answer import Answer, Ask
from toad.client.input_attention import InputAttention
from toad.client.interactive_dialog import (
    ConfirmDialogField,
    DialogAccepted,
    DialogCancelled,
    DialogDeclined,
    DialogSpec,
    MultiSelectDialogField,
    NumberDialogField,
    SingleSelectDialogField,
    TextDialogField,
)
from toad.qt.interactive_dialog import QtInteractiveDialog
from toad.widgets.interactive_dialog import PromptDialog


def _sample_elicitation_schema() -> schema.ElicitationSchema:
    return schema.ElicitationSchema(
        title="Release options",
        description="Configure the build before shipping.",
        required=["target", "features", "retries"],
        properties={
            "target": schema.ElicitationStringPropertySchema(
                type="string",
                title="Target host",
                one_of=[
                    schema.EnumOption(const="ts-gaming", title="Gaming PC", description="Primary bus"),
                    schema.EnumOption(const="laptop", title="Laptop", description="Secondary bus"),
                ],
                default="ts-gaming",
            ),
            "features": schema.ElicitationMultiSelectPropertySchema(
                type="array",
                title="Features",
                min_items=1,
                items=schema.TitledMultiSelectItems(
                    any_of=[
                        schema.EnumOption(const="apk", title="Android APK"),
                        schema.EnumOption(const="tui", title="Textual TUI"),
                        schema.EnumOption(const="qt", title="Desktop Qt"),
                    ]
                ),
            ),
            "confirm_push": schema.ElicitationBooleanPropertySchema(
                type="boolean",
                title="Push immediately",
                default=True,
            ),
            "retries": schema.ElicitationIntegerPropertySchema(
                type="integer",
                title="Max retries",
                minimum=1,
                maximum=5,
                default=2,
            ),
            "note": schema.ElicitationStringPropertySchema(
                type="string",
                title="Release note",
            ),
        },
    )


def test_dialog_spec_parses_acp_elicitation_questions_and_ask() -> None:
    spec = DialogSpec.from_elicitation("Ship it?", _sample_elicitation_schema())
    assert spec.title == "Release options"
    assert spec.message == "Configure the build before shipping."
    assert [type(f) for f in spec.fields] == [
        SingleSelectDialogField,
        MultiSelectDialogField,
        ConfirmDialogField,
        NumberDialogField,
        TextDialogField,
    ]
    assert not spec.is_quick_choice

    # Multi-question JSON (ask_question / AskUserQuestion shape)
    raw = json.dumps({
        "title": "Design choices",
        "questions": [
            {
                "id": "layout",
                "question": "Which layout?",
                "options": [
                    {"label": "Inline", "value": "inline", "description": "Under composer"},
                    {"label": "Modal", "value": "modal"},
                ],
            },
            {
                "id": "platforms",
                "question": "Which platforms?",
                "is_multi_select": True,
                "options": ["TUI", "Desktop Qt", "Android"],
            },
        ],
    })
    parsed = DialogSpec.parse(raw)
    assert len(parsed.fields) == 2
    assert isinstance(parsed.fields[0], SingleSelectDialogField)
    assert isinstance(parsed.fields[1], MultiSelectDialogField)
    assert parsed.fields[0].allow_other is True
    assert [opt.value for opt in parsed.fields[1].options] == ["TUI", "Desktop Qt", "Android"]

    # Existing Ask lifts into quick single-choice dialog
    ask = Ask("Allow write?", [Answer("Allow once", "allow_once", "allow_once"), Answer("Reject", "reject", "reject_once")])
    lifted = DialogSpec.parse(ask)
    assert lifted.is_quick_choice
    assert [opt.value for opt in lifted.fields[0].options] == ["allow_once", "reject"]

    # Outcome -> ACP elicitation response
    accepted = DialogAccepted({"target": "laptop", "features": ["apk", "qt"], "note": None}).to_elicitation_response()
    assert accepted.action == "accept"
    assert accepted.content == {"target": "laptop", "features": ["apk", "qt"]}
    assert DialogDeclined().to_elicitation_response().action == "decline"
    assert DialogCancelled().to_elicitation_response().action == "cancel"


def test_qt_interactive_dialog_quick_choice_and_multi_field_validation() -> None:
    app = QApplication.instance() or QApplication([])
    host_window = QWidget()

    class _TestAttention(InputAttention):
        def publish_title(self, title: str) -> None:
            pass

        def deliver(self, title: str, message: str, *, sound: str | None = None) -> None:
            pass

        def schedule_blink(self, interval: float, tick) -> object:
            return None

        def cancel_blink(self, timer: object) -> None:
            pass

    fake_app = SimpleNamespace(input_attention=_TestAttention(SimpleNamespace()))
    dialog = QtInteractiveDialog(fake_app, host_window)

    # 1. Quick single-choice commits in 1 tap.
    outcomes: list[object] = []
    quick_spec = DialogSpec.from_ask(
        Ask("Approve command?", [Answer("Yes", "yes"), Answer("No", "no")])
    )
    dialog.open_dialog(quick_spec, outcomes.append)
    assert dialog.dialog_open
    buttons = [b for b in dialog.findChildren(QPushButton) if b.text() in ("Yes", "No")]
    assert len(buttons) == 2
    buttons[0].click()
    assert outcomes == [DialogAccepted({"answer": "yes"})]
    assert not dialog.dialog_open

    # 2. Multi-field elicitation: missing required multi-select blocks submit and shows error.
    outcomes.clear()
    spec = DialogSpec.from_elicitation("Ship?", _sample_elicitation_schema())
    dialog.open_dialog(spec, outcomes.append)
    assert dialog.commit_dialog() is False
    assert "features" in dialog.dialog_errors
    assert not outcomes

    # Toggle two checkboxes and submit cleanly.
    boxes = [box for box in dialog.findChildren(QCheckBox) if box.text() in ("Android APK", "Desktop Qt")]
    assert len(boxes) == 2
    for box in boxes:
        box.setChecked(True)
    # Also type a release note into the last QLineEdit.
    edits = dialog.findChildren(QLineEdit)
    edits[-1].setText("all green")
    assert dialog.commit_dialog() is True
    assert outcomes == [DialogAccepted({
        "target": "ts-gaming",
        "features": ["apk", "qt"],
        "confirm_push": True,
        "retries": 2,
        "note": "all green",
    })]
    assert not dialog.dialog_open
    host_window.close()
    app.processEvents()


@pytest.mark.asyncio
async def test_textual_prompt_dialog_renders_and_submits_multi_select() -> None:
    class _DialogApp(App):
        def compose(self) -> ComposeResult:
            yield PromptDialog()

    outcomes: list[object] = []
    spec = DialogSpec.from_questions(
        [
            {
                "id": "mode",
                "question": "Pick mode",
                "options": ["fast", "thorough"],
                "allow_other": False,
            },
            {
                "id": "targets",
                "question": "Pick targets",
                "is_multi_select": True,
                "options": ["tui", "qt", "android"],
                "allow_other": False,
            },
        ],
        title="Build setup",
    )
    app = _DialogApp()
    async with app.run_test() as pilot:
        dialog = app.query_one(PromptDialog)
        dialog.open_dialog(spec, outcomes.append)
        await pilot.pause()
        assert dialog.display is True
        # Missing required multi-select fails validation before toggling.
        assert dialog.commit_dialog() is False
        assert "targets" in dialog.dialog_errors

        dialog.toggle_dialog_option("targets", "tui", True)
        dialog.toggle_dialog_option("targets", "android", True)
        await pilot.click("#dialog-submit")
        await pilot.pause()
        assert outcomes == [DialogAccepted({"mode": "fast", "targets": ["tui", "android"]})]
        assert dialog.display is False

        # Cancel via Escape / button produces DialogCancelled.
        outcomes.clear()
        dialog.open_dialog(spec, outcomes.append)
        await pilot.pause()
        await pilot.click("#dialog-cancel")
        await pilot.pause()
        assert outcomes == [DialogCancelled()]
        assert dialog.display is False
