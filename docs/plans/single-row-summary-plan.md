# Keep transcript headers inside one physical row

Owner: toad-close-lifecycle. Await Tristan approval before scroll-path edits.

## Source and evidence
`RichLineRenderer.summary` writes `_fit(block.text, self.width)` into one Segment. `_fit` only clips Python characters and preserves embedded line breaks. `PlainRowCount.one_row` declares Summary/Divider/Gap as one row. Thus a multiline command has one allocated row but can write multiple physical terminal lines. Both styled workers and immediate plain rows use the same RichLineRenderer; divider spans also use `_fit`.

Existing ModuleSyntaxIndex census across Toad and Core production roots records Summary construction, both `_fit` consumers, renderer and height consumers in `.artifacts/runtime-build/header-source-ast.log`. MRO dispatch and Rich terminal behavior need semantic/live reading, not an AST proof. toad-ui-2's retained pageup.png and compositor capture are the reproducer; no synthetic inputs or replacement app.

## Proposed owner change
Make the existing row fitter honor its one-row contract for both Summary and Divider: normalize source line breaks/tabs through the existing plain-line mechanism, then clip by Rich terminal-cell width. Preserve full native command/title data and disclosed body, actions/styles, source history, worker/plain sharing and row count. No changes to transcript_fragments.py, transcript_history.py, tool_output.py or #600/#604 ordering/DM mechanisms. No second title formatter or widget state.

## Acceptance
In the actual installed application on the retained session and isolated display, held PageUp across a saved multiline Bash command must paint one clipped header without text escaping into the sidebar. The disclosure must preserve the complete command. Confirm both initial plain and prepared rendering. Record physical message-area evidence; no fake response, fixture or test app. This is a rendering correctness fix, not a 16 ms performance claim.
