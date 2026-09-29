# T4 App TabOrder + clipboard readiness

Product and installed UI baseline: main b472e487/Toad128, implementation b358ae4.
Own persistent tree: /home/ts/wt/toad-t4-tab-clipboard-sol-20260928.
Parent owns merge and paired live installation. Carver owns Conversation/Agent;
Tesla/workspace owner owns resources and global rich-surface lifetime.

## Final current-main integration

Parent132 landed as main b4bdae1657a819dd943ed1fbd5a2b684c2683019.
This branch is rebased onto it and preserves its direct ToolRequest callers,
updated lock/pins and all predecessor owners. The new installed acceptance uses
core287 4510dddf737da3d445ba20d90c79f3dcb3f08b27 plus merged Textual8
c9743801c98dc570f82f82e25915ecce89800f4b, exactly the merged project pins.

**6 passed in 50.98s**, one complete focused invocation: state/new-case/deletion
contracts, real LinuxDriver/private-X11/OSC52 copy-paste-failure-PNG pilot,
installed tab-history controls and interleaved tab-order UI. No paid/provider
prompt, source/editable import, CI wait or live change. Shared per-class/AST
ratchet still has zero positive deltas against new main; App -91, Prompt -5,
preview0. All scope implementation and deletion are complete; no blocker.

The earlier acceptance and NRA structural audit below remain as history. They
are not substituted for this final installed current-main result. Full archived
NRA JSON is retained locally; the final update changes integration/dependency
context, not this slice's production implementation.

## Original installed acceptance

Noneditable Toad wheel in own Python3.14 venv; no PYTHONPATH/editable overrides.
Installed framework c9743801c98dc570f82f82e25915ecce89800f4b (Textual8) and
core280 487ebb9ec4468a70a92fc172dd5f2f50950a3c87. Product pyproject pins stay
under parent's paired-release ownership; this slice does not restore a feature dependency.

- State/new-case/deletion guards and native pilot: **4 passed**, 10.25s.
- Actual tab-history and interleaved tab-order UI pilots: **2 passed** in the
  preceding batch. Main/channel/preview Back/Forward, close pruning, direct
  selection, drafts, scrollbar, and same-mode repeated visits exercised.
- Actual LinuxDriver/PTY keyboard Ctrl+Y + Ctrl+V, 79,200-character Unicode text:
  private X11/xclip System copy/paste; display-free Terminal OSC52 + cache paste;
  genuine missing-xclip failure after native selection switches to Terminal.
  Native success emits zero OSC52; terminal/failure emit exactly one full copy.
- Actual native PNG capture still returns the original 68-byte PNG.
- No provider prompt/call, no live/shared tree changes, CI deferred.

Commands: `python -m pytest -q tests/test_tab_clipboard_owners.py
 tests/clipboard_native_pilot.py`, plus actual installed pilots
`tests/tab_history_controls_pilot.py` and `tests/tab_order_pilot.py`.
Private test roots and children are bounded and retired.

## Deletion and semantic ownership

TabOrder owns ordered logical identities, all visit/cursor state, pruning,
previous/history traversal and change signal. New logical tab kind requires
zero order/history implementation edits. It does not own a second workspace catalog.
Clipboard uses existing core DeclaredFamily with common Textual local-value
ownership; a new copy transport needs one declared subclass and zero
App/Prompt dispatch or separate registry entries. Prompt text paste is migrated.

Deleted App private lists/cursor/history methods and clipboard support flag;
all retained callers migrated. Deleted 106 lines of mocked clipboard tests.
App AST span 1803 -> 1712, PromptTextArea 368 -> 363;
Conversation2829 and Agent1354 unchanged. FilePreviewScreen26 ->26 uses its
existing framework name plus required containing-directory project context.

Actual-path failures found and corrected: missing Markdown preview context,
same-tab history cursor not moving, and xclip returning text for unsupported
image/png. Non-PNG selection now reaches text paste; valid PNG bounds/storage
remain with existing image owner. Fixture Screen mounting and child exit-reaping
failures are retained locally and corrected, not represented as product passes.

## Guards and audit

Shared per-class/AST ratchet: **zero positive deltas**, App -91,
PromptTextArea -5, FilePreviewScreen0. New owners have no pre-merge baseline;
no guard waiver or class-growth offset. See ratchet-summary.json.

Bounded NRA package + merged-core context scan: normal full JSON, exit0,
12.569s, 412 indexed files, 31 existing raw findings. No finding evidence points
to changed production paths. R1 mapping_read/unmodeled_record_shape and
redundant_type_check entries are absent in this report; owner observations and
limitations recorded in nra-summary.json. No whole-package-clean or native
codemod proof claim. Full compressed audit retained locally for review.

No remaining blocker for this assigned slice. Workspace/resource admission
and operational detach work remains independently assigned. Parent can merge
this PR and include it in the next paired live installation.
