"""Rule settings prepare all choices and submit through the actual form."""

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.configure_rule_gate import ThreadRuleGateCliCommand
from agent_comms.team.rule_deal import RequiredRuleCheckPolicy
from toad.forms.editors import ChoicesEditor
from toad.widgets.comms_command_dialog import (
    ApplyCommandButton,
    CommandDialog,
    CommandPreparation,
)


async def test_rule_settings_choices_arrive_after_mount_and_apply(workspace):
    async with workspace.app(size=(110, 55)) as ui:
        app = ui.textual[0]
        command = ThreadRuleGateCliCommand(name="settings-peer")
        action = TargetAction((command,), ("settings-peer",), ThreadRuleGateCliCommand)
        observed = await app.preparation.run_thread(app.coordination_access.observation.observed)
        accepted = []
        dialog = CommandDialog(action, "settings-peer", action.editable_fields, observed.core)
        app.push_screen(dialog, accepted.append)
        await ui.until(lambda: dialog.form.is_mounted, why="the rule settings form to mount")
        await ui.until(lambda: not CommandPreparation.running_on(dialog),
                       why="the rule settings choices to arrive")
        for name in ("audit", "confirmation"):
            editor = dialog.form.values[name].editor
            assert isinstance(editor, ChoicesEditor)
            assert set(label for label, _ in editor.displayed_options()) >= {"off", "required"}
        button = dialog.query_one(ApplyCommandButton)
        button.scroll_visible(animate=False, immediate=True)
        await ui.until_clickable(button, why="the rule settings Apply button")
        assert await ui.textual[1].click(button)
        await ui.until(lambda: bool(accepted), why="rule settings Apply to submit without an error")
        applied = action.edited(accepted[0]).with_confirmation(False)
        assert applied.bound[0].audit is RequiredRuleCheckPolicy
        assert applied.bound[0].audit_confirmation is RequiredRuleCheckPolicy
