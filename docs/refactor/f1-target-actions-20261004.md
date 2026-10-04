# F1 typed target actions: Toad consumer claim

Draft source batch; no Ready/live claim. Core is the declaration and result owner. This paired PR migrates target_commands.py, thread_actions.py, widgets/comms_command_dialog.py and original fixture callers to its typed TargetAction and editable field attributes. Route recapture, form acceptance/cancellation, request task joining, current target membership and slash/menu lifetimes remain original owners.

Before editing, read the Core declaration/binding/result/FieldCodec family and enumerate full Core/Toad/dependency AST with the existing refactor-audit collector. No raw action/result shape will remain in this in-process API. CLI JSON encoding stays Core boundary. Installed actual action/form/slash verification comes after the complete joined source. No new environment, native artifact or provider replay. Frozen421 remains unchanged.
