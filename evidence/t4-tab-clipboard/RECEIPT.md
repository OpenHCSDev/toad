# T4 App TabOrder + clipboard readiness

Product and installed UI baseline: main b472e487/Toad128, implementation b358ae4.
Own persistent tree: /home/ts/wt/toad-t4-tab-clipboard-sol-20260928.
Parent owns merge and paired live installation. Carver owns Conversation/Agent;
Tesla/workspace owner owns resources and global rich-surface lifetime.

## Installed acceptance

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
