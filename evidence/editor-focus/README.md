# PR217 editor and retained-source checkpoint

24 production lines deleted; 55 added across five files. The installed receipt
identifies the complete source by 267 matching Python file hashes and wheel SHA.
Main211 `3b019be07ddcde7201a4a3332f7083bc127ee39b` was normally merged before this
change. This checkpoint is not installed globally.

## Reproducer and ownership

The provider-free LinuxDriver journey physically clicks two tabs backed by real
105-record saved Pi JSONL files, uses production transcript paging and rendering,
and edits while an actual `WorkingTranscript` source operation is admitted.

Before the focus change, printable `other` reached PromptTextArea but Left left
the caret at column five. The key interval shows focus changing to Window and
its scroll binding receiving the key. The request trace identifies
`Conversation.on_click -> refresh_block_cursor`: a queued click on the previous
history requested its Window after another workspace source was selected.
The later origin-observation run passed editing but timed out at shutdown; it
is counterevidence to a deterministic failure, not an acceptance pass.

The fix admits clicks through the existing SessionView current-source contract
and resolves block focus synchronously through Textual Screen.set_focus. It
adds no editor flag, focus timestamp or binding override. Both click selection
and keyboard block navigation inherit the existing refresh_block_cursor route.
Arendt approved these navigation methods; canonical turn/input/cancel are
unchanged.

The same journey first exposed a separate main211 source restoration crash:
NativeSessionSurface inferred a native actor from any TranscriptHistory widget,
then refresh_revealed(None) called get_transcript_page. A local saved-file pager
is a valid resource without an ACP actor. Conversation now delegates to the
actual AgentPresentation; native restoration remains with TranscriptPresentation,
and local restoration resumes only ParkedSourceTranscript through its declared
state action. Schrodinger approved that narrow state action. Original native
source validation, retirement and operation witnesses are unchanged. A new
AgentPresentation implements its existing restore contract; no surface roster
or alternative reader is added (IMPL-4, IDEN-3, TIME-3).

## Actual results

- Installed65/Coreab simple physical editor/Tab/A/B/A plus one-write
  `abcd + Left + Backspace + Delete` passed: `ab`, caret two.
  This disproved the initial simple printable-handoff hypothesis in that run.
- Source candidate saved-history journey exited zero.
- Isolated installed candidate with read-only staged Core720629 and Textual412
  dependencies exited zero: 38 phases, 142 editing-key observations during
  WorkingTranscript. Draft, caret, actual document and undo owner identities
  survived A/B/A; undo and subsequent deletion/arrows passed. The same editor
  owned the key chain at every completed editor phase.
- An initial installed return assertion ran before the queued Focus event had
  settled. The driver now waits for actual editor focus as well as the expected
  document/caret, then retains the focus assertion. Shutdown consumes terminal
  output while waiting so this test cannot block its child on a full PTY.

No ACP/native process or provider prompt was started. All roots were disposable
private fixture roots; no live-root owner lifecycle operation was used. The
actual production app and LinuxDriver remain in the path; observations wrap
focus methods and forward them unchanged.

Reproduce from the owned installed wheel:

```sh
EDITOR_KEY_EVIDENCE="$PWD/.artifacts/editor-focus-217/installed-owned-navigation-ready" \
TMPDIR="$PWD/.artifacts/editor-focus-217" \
PYTHONPATH="$PWD/tests:$PWD/.artifacts/editor-focus-217/test-dependencies" \
timeout 55s .artifacts/editor-focus-217/package/runtime/bin/python \
  tests/editor_key_terminal_journey.py --saved-history
```

The isolated runtime imports its own installed Toad wheel. Its .pth only reads
dependencies from the parent's unused paired stage; that stage is not modified.
The wheel and runtime are owned evidence artifacts. Other disposable package
caches can be removed after source/evidence publication.

## Bounded audit and limits

The eleven-file TC1 crossing receipt compares pre129
`436514d875c01964f3a4fea6919f1892e60c73f8`, main211 and this working source.
Absent pre129 files are explicitly listed. Main211 -> candidate: None identity
224 -> 223; foreign absence probes 72 -> 72; boolean-chain terms 47 -> 47.
All four dispatch measures pass per-file and per-function ratchets. The existing
five action-name cases in Conversation.check_action are unchanged Textual
binding eligibility; this receipt does not refactor parent-owned turn policy.
The new negative SessionView.is_current call is an explicit canonical lifecycle
query, not another absent-state inference. Full TC1 remains incomplete:
pre129 had 147 None identity checks and 59 foreign probes on the same paths.

Native restoration's moved callback still needs affected installed native
acceptance. Active/post-cancel editor input, whole TC1/T9, large-history physical
lazy-end void/video/CPU and final warm first-paint work remain open. This local
saved-file journey does not claim their closure or reproduction of the user's
exact installed failure.
