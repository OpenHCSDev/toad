"""Actual Toad command/member dialogs; no command execution or invented state."""

import pytest
from textual.widgets import Button

from agent_comms.cli_command import TargetAction
from agent_comms.cli_verbs.fork import ForkCliCommand
from agent_comms.cli_verbs.new import NewThreadCliCommand
from agent_comms.field_codec import MalformedRecord
from agent_comms.repo import Checkout
from agent_comms.thread_management import ChangedTags, GivenTags, InheritedTags
from support.ui import TextualUi
from support.workspace import Workspace
from toad.forms.editors import LineEditor, OptionalEditor, UnionEditor, ValueEditor
from toad.widgets.comms_command_dialog import CommandDialog, CommandMemberDialog


async def show_command(ui: TextualUi, definition: TargetAction) -> CommandDialog:
    dialog = CommandDialog(definition, 'private project', await definition.prepare_fields())
    ui.app.push_screen(dialog)
    await ui.until(lambda: dialog.is_attached and all(
        view.editor.is_mounted for view in dialog.form.values.values()
    ), why='the real command fields to mount')
    return dialog


async def supply(ui: TextualUi, editor: ValueEditor, text: str) -> None:
    assert isinstance(editor, LineEditor)
    editor.value = text
    editor.commit()
    await ui.step()


async def open_member(ui: TextualUi, command: CommandDialog) -> CommandMemberDialog:
    editor = command.form.values['tags'].editor
    assert isinstance(editor, UnionEditor)
    editor.scroll_visible(animate=False, immediate=True)
    await ui.step()
    assert await ui.pilot.click(editor)
    await ui.until(lambda: isinstance(ui.app.screen, CommandMemberDialog),
                   why='the actual member transaction')
    member = ui.app.screen
    assert isinstance(member, CommandMemberDialog)
    return member


@pytest.mark.parametrize('text,expected', [('', frozenset()), ('chosen', frozenset({'chosen'}))])
async def test_new_dialog_keeps_missing_name_and_tags_distinct_from_explicit_empty(
    workspace: Workspace, text: str, expected: frozenset[str]
) -> None:
    binding, = NewThreadCliCommand.project_bindings(workspace.comms, Checkout(workspace.project))
    definition = TargetAction((binding,), (), NewThreadCliCommand)
    async with workspace.app(session=False) as ui:
        dialog = await show_command(ui, definition)
        assert 'name' not in dialog.arguments()
        assert 'tags' not in dialog.arguments()
        assert dialog.query_one('#command-apply', Button).disabled
        with pytest.raises(MalformedRecord):
            definition.edited(dialog.arguments())
        name = dialog.form.values['name'].editor
        assert isinstance(name, OptionalEditor)
        name.holds_value.value = True
        await ui.step()
        await supply(ui, name.member, 'new-child')
        assert 'tags' not in dialog.arguments()
        with pytest.raises(MalformedRecord):
            definition.edited(dialog.arguments())
        tags = dialog.form.values['tags'].editor
        assert isinstance(tags, OptionalEditor)
        tags.holds_value.value = True
        await ui.step()
        await supply(ui, tags.member, text)
        completed, = definition.edited(dialog.arguments()).bound
        assert completed.name == 'new-child'
        assert completed.tags == GivenTags(expected)
        await ui.until(lambda: not dialog.query_one('#command-apply', Button).disabled,
                       why='explicit name and membership to enable Apply')
        # Completing a form must not create or start the command's thread.
        assert 'new-child' not in workspace.comms.registry
        dialog.dismiss()


async def test_fork_member_selection_apply_reopen_cancel_and_native_parent_refresh(
    workspace: Workspace,
) -> None:
    parent = workspace.thread('original-parent', 'old')
    binding = ForkCliCommand.thread_binding(parent)
    definition = TargetAction((binding,), (parent.name,), ForkCliCommand)
    async with workspace.app(session=False) as ui:
        command = await show_command(ui, definition)
        assert 'parent' not in command.form.values
        assert 'name' not in command.arguments()
        name = command.form.values['name'].editor
        assert isinstance(name, OptionalEditor)
        name.holds_value.value = True
        await ui.step()
        await supply(ui, name.member, 'fork-child')
        untouched, = definition.edited(command.arguments()).bound
        assert untouched.tags == InheritedTags()
        assert untouched.tags.for_child(frozenset({'later'})) == frozenset({'later'})

        member = await open_member(ui, command)
        given = next(choice for choice in member.members.choices() if choice.declaration is GivenTags)
        member.selector.value = given
        await ui.until(lambda: member.draft.selection is given and 'value' in member.form.values,
                       why='GivenTags text editor')
        assert member.selector.value is given
        await supply(ui, member.form.values['value'].editor, 'old')
        assert await ui.pilot.click(member.apply_button)
        await ui.until(lambda: ui.app.screen is command, why='one GivenTags commit')
        assert command.state.get_resolved_value('tags') == GivenTags(frozenset({'old'}))

        member = await open_member(ui, command)
        retired = member.draft.state
        changed = next(choice for choice in member.members.choices() if choice.declaration is ChangedTags)
        member.selector.value = changed
        await ui.until(lambda: member.draft.selection is changed and set(member.form.values) == {'add', 'remove'},
                       why='ChangedTags required record fields')
        assert member.apply_button.disabled
        assert member.draft.arguments() == {}
        retired.update_parameter('value', 'retired-input')
        await ui.step()
        assert member.draft.arguments() == {}
        assert member.apply_button.disabled
        add = member.form.values['add'].editor
        remove = member.form.values['remove'].editor
        assert isinstance(add, OptionalEditor)
        assert isinstance(remove, OptionalEditor)
        add.holds_value.value = True
        await ui.step()
        await supply(ui, add.member, '["new"]')
        assert member.apply_button.disabled
        remove.holds_value.value = True
        await ui.step()
        await supply(ui, remove.member, '["old"]')
        expected = ChangedTags(frozenset({'new'}), frozenset({'old'}))
        assert member.draft.complete() == expected
        assert await ui.pilot.click(member.apply_button)
        await ui.until(lambda: ui.app.screen is command, why='one ChangedTags commit')
        assert command.state.get_resolved_value('tags') == expected
        assert set(command.state.direct_parameter_paths('tags')) == {
            command.state.parameter_structure.path('tags.add'),
            command.state.parameter_structure.path('tags.remove'),
        }
        assert 'tags.tags' not in command.state.parameters
        await ui.step()
        assert str(command.form.values['tags'].editor.label) == changed.label
        assert command.form.values['tags'] in tuple(command.form.observing_values({'tags.add'}))
        completed, = definition.edited(command.arguments()).bound
        assert completed.tags == expected
        assert completed.parent == parent.name

        member = await open_member(ui, command)
        assert member.draft.selection.declaration is ChangedTags
        assert member.draft.complete() == expected
        await supply(ui, member.form.values['add'].editor, '["cancelled"]')
        assert await ui.pilot.click(member.query_one('#union-cancel', Button))
        await ui.until(lambda: ui.app.screen is command, why='member transaction cancelled')
        assert command.state.get_resolved_value('tags') == expected
        assert 'fork-child' not in workspace.comms.registry
        with pytest.raises(ValueError, match='Target-bound'):
            await command.refresh_catalogs({'parent': 'not-the-captured-parent'})
        with pytest.raises(ValueError, match='not offered'):
            await command.refresh_catalogs({'unoffered': 'not-a-command-field'})
        command.dismiss()


async def test_actual_settings_observes_a_changed_ancestor(workspace: Workspace) -> None:
    from toad.screens.settings import SettingsScreen

    async with workspace.app(session=False) as ui:
        settings = SettingsScreen()
        ui.app.push_screen(settings)
        await ui.until(lambda: settings.is_attached, why='the actual settings form')
        width = settings.form.values['ui.column_width']
        assert width in tuple(settings.form.observing_values({'ui'}))
        assert width in tuple(settings.form.observing_values({'ui.column_width'}))
        settings.dismiss()
