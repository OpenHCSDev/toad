# TL0A — active code-bearing deletion surface

Owner Copernicus; own persistent ~/wt/toad-tl0a-legacy-deletion-20260928,
branch refactor/tl0a-legacy-deletion, stacked on paired1071824fb7. Existing114/115
implementations are inherited, not duplicated. This is an active draft: the
whole TL0A surface remains open until the remaining package/caller closure below.

## Coherent deletion published

- Delete unimported SessionSidebar/SessionRow and their transport-only
  SessionPresentation. Shared Comms wire-thread rows are the real mounted path.
- Delete ThreadStatusRow.update_thread forwarding API; sole direct test caller
  uses existing prepare_thread_row and apply_thread_preparation.
- Delete dead code_analyze, gist, option_content, os, widgets/version and
  widgets/welcome modules. T8 already deleted danger_warning. Keep render_server:
  render_zmq actually launches it with python -m; PR50 browser work is independent.
- Apply TD3's documented default (this fork is the Comms client): delete old
  models/currentModelId/availableModels parsing; retain current configOptions.
  T2 owns the later full nominal ACP boundary; no alternate decoder is added.

No durable data/schema or external ACP/Pi format changed. Removed runtime
presentation had no production consumer outside its unused sidebar. Source
+3/-338; new guards and migrated row test protect deleted APIs/current rendering.

## Acceptance

Wheel built and installed only into owned target, paired with core58bfad3 and
Textual16ede. Shared Channels pilot passes actual new/loading/warm frames, one
retained tree, rows/tasks and independent right panel. Row-caller pilot passes
shared rows/navigation/sort/collapse. Model picker passes filtering/focus/history,
failed selection and resize. New AST/module guards pass. No provider/live calls.

## Remaining full TL0A closure / ownership boundaries

- MCP package binding and negotiation deletion: TL0 owns mcp_inventory,
  mcp_decision and their screens. Core already packages MCP inside the verified
  native Pi tree (prepare-native-import-boundary.py). Bind inventory/decisions
  to that pinned owner before deleting positive-decision capability negotiation;
  do not simply remove checks while accepting arbitrary configured CLI programs.
- Darwin T1 currently edits screens/main.py, settings schema/tree,
  widgets/comms_sidebar.py and widgets/conversation.py. TL0 does not edit these
  files concurrently. Requested narrow handoff: remove production test hook,
  remove in_out_only accessor and let its retained tests use visible_categories,
  and coordinate retirement of mcp.node_path/cli_path settings/caller args when
  TL0's pinned package API is available. Handoff is requested, not claimed accepted.
- Parent T6/T4 owns rendering/app marker cleanup during its existing surfaces;
  no duplicate renderer or command implementation. TL0B/T5 remain queued after
  T2/T6 as dispatch requires. Broad final marker/dead-module guards land when all
  owners finish; this draft's guard covers the mechanism already deleted.

Latest dispatch ledgera32652a is integrated in107. Parent owns combined merging,
D22 conversion and activation. CI deferred; do not equate this active draft with
whole-surface completion.
