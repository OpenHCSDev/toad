# Actual default editor input: reproduced Delete failure

Source boundary: Core `000a31c562b6d048e26e288b24fcd3f1ac64f803`, Toad
`173901b9329af36116158ec492db839af7d872c6`, Textual
`65053c5a2df12249ef1c4193beeff7023c1f75d7`, SDK0.12.1, nativee36.
Default installed launcher through isolated st/Xvfb; only Toad's UI SQLite
state is copied. Original saved native state and selected backend are used.

Raw evidence:
`/home/ts/.cache/agent-scratch/toad-editor-focus-227-20260930-run02`.
The 45.946-second capture has all seven physical phase markers. The source
and process identity receipts before/after are byte-equal for the original
41,270,257-byte parent and 13,212,421-byte existing child. Cleanup reports
zero remaining owned processes and zero errors. No provider calls, prompt
submissions, public mutations or replay were performed.

| Physical phase | Selected view | Actual draft / caret | Focus |
| --- | --- | --- | --- |
| typed | parent session-1 | `abcdef` / 6 | original PromptTextArea |
| edited | parent session-1 | `abcef` / 4 | same original PromptTextArea |
| history-edit | parent session-1 | `abceabceff` / 8 | same original PromptTextArea |
| child-open | child session-2 | empty / 0 | child's separate PromptTextArea |
| parent-return-edit | parent session-1 | `abceabceabcefff` / 12 | original PromptTextArea |
| channel-edit | comms-1 | `abcef` / 4 | separate ChannelTextArea |
| channel-return-edit | parent session-1 | `abceabceabceabceffff` / 16 | original PromptTextArea |

After the first typed phase, Left/Left/Backspace/Delete/Right should produce
`abcf` / 4. Backspace and Left/Right worked; Delete did not delete. Physical
`phase-edited.png` shows the Help panel opening from that keystroke. Focus
remained on the correct native editor through each observed return. Final
Ctrl+C cleared the isolated drafts, and the original user state was protected.

The installed st binary matches the local source binary (SHA256 a3cd8502…);
its normal keypad Delete emits CSI P. The actual installed native Textual
parser decodes CSI P as F1 and application-keypad CSI3~ as Delete. This
locates a terminal input-mode boundary rather than a demonstrated focus
mirror. The framework driver lifecycle fix is tracked in Textual draft PR14,
source `4e8d13d21`, owned by Kepler. Heisenberg227 integrates the workflow.
Application-keypad mode ownership is shared through Driver and inherited by
full-screen/inline consumers; no F1 alias, TERM branch or per-editor flag.

This is a FAIL receipt, not readiness. Intermittent Backspace/arrow failure
was not reproduced in this bounded run; it is not claimed fixed. The affected
installed candidate editing journey is still required.

Run01 counterevidence is preserved: the original wrapper omitted `--actions`
and recorded only startup/idle. That attempt proves no physical editing
behavior. The corrected wrapper supplies the actions and requires every
physical marker. No hidden deletion or successful-retry claim substitutes for
its failed test coverage.

Production lines deleted in this Toad diagnosis: **0**. Diagnostic tool fields
replace one line, adding native focus and draft object identities only.

## Subsequent scoped keypad acceptance

The preserved baseline above remains a FAIL. The sole corrected physical
candidate capture is
`/home/ts/.cache/agent-scratch/toad-editor-focus-227-20260930-candidate02`.
Its 46.042-second journey uses Toad `9354b391880980c9c987f421e16b9a1fd59b3f3b`,
the same Core000/SDK0.12.1/nativee36, and Textual code
`4e8d13d21bf98e4ad52e610277d7d06c9035ccfa`. Textual publication head
`f0051410e33ac51056739fb6d5868b73f7dc41ce` adds the reviewed receipt only;
its production source is byte-identical to the installed candidate.

Agent and channel physical edited frames show **abcf / caret4**, without
opening Help. Parent editor `140425345526160` remains the focused native
editor on both child/parent and channel/parent return, retaining and extending
its draft. Native parent and child source/process receipts are byte-equal;
all seven phase markers completed and cleanup reports zero remaining owned
processes and zero errors. No input was submitted or replayed, no provider
was called, and the default installation was not changed.

**Scoped Delete PASS; whole focus workflow NOT READY.** The body click at
(750,350) hit an outbound `comms428` link, opening a third tab and its own
editor. The strict additive-parent/editor-identity assertions failed, and
`editing-acceptance.json` remains unchanged. This is a physical selection
coverage gap, not evidence that the original parent editor was replaced.
Heisenberg227 retains the intended pure history-click/PageUp focus gap.
Intermittent Backspace/arrow failure was not reproduced or claimed fixed.

[Machine receipt](editor-keypad-candidate-assessment.json) records all
physical frame paths/hashes, exact native focus/ancestor/draft identities,
installed source and metadata hashes before/after, protected original
receipts, and Toad9354-to-bf561/718030 production source equivalence. Those
later Toad publication commits change evidence only. Candidate01's missing
activation metadata failure occurred before UI launch and is protected;
the builder corrected metadata without changing packages, source or route.
