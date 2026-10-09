# Editor key lifecycle: scoped ready checkpoint

Owner: Kepler; joint Toad TC1/T9 integration owner: Heisenberg227.
No open Textual PR overlapped this input boundary at claim time.

## Actual failing path

Default Core000/Toad173/Textual650/nativee36, actual retained 41 MB
`nra-architecture`, existing child `nra-domain-mapping`, actual isolated
st/Xvfb and an isolated SQLite copy of Toad UI state. No provider calls,
prompt submission, public mutation or native input replay.

Raw evidence:
`/home/ts/.cache/agent-scratch/toad-editor-focus-227-20260930-run02/capture`.
The 45.946-second physical journey completed typing, history selection,
child/parent tab return, channel opening and agent return. Native focused
editor identities are correct at each phase. `abcdef` followed by Left,
Left, Backspace, Delete, Right produced **abcef**, not **abcf**, in both
agent and channel editors. The physical edited frame shows the Help panel
opening. Original native source hashes and process identities are unchanged;
recorder cleanup has no remaining owned processes or errors.

Installed st binary SHA256
`a3cd85021357789a10f936690671be8dad25c620eb580ffb6f8e43e3620570c2`
matches `/home/ts/programs/st/st`. Its source configuration sends CSI P for
Delete in normal keypad mode and CSI 3~ in application keypad mode. The
actual installed Textual parser maps CSI P to F1 and CSI 3~ to Delete.
Baseline Linux full-screen and inline application startup never entered
application keypad mode. No focus mirror or editor-specific key policy is
needed to explain this failure.

## Implemented ownership closure

The terminal driver owns entry and retirement of application keypad mode.
Share its native enter/leave operations through the existing Driver owner;
both Linux full-screen and inline lifecycle consumers call that contract.
Suspension/resumption already delegates to the same stop/start methods.
Do not remap F1, add a TERM string switch, create a focus flag, or patch each
editor. Keep the canonical parser and native Screen focus authority intact.
This is an IMPL-13 lifecycle closure, not a compatibility reader.

[XTerm control sequences](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html)
declares ESC = for application keypad and ESC > for normal keypad.

Code head: `4e8d13d21bf98e4ad52e610277d7d06c9035ccfa`.
Production diff: **12 added lines, 0 deleted lines**, across
`src/textual/driver.py`, `src/textual/drivers/linux_driver.py`, and
`src/textual/drivers/linux_inline_driver.py`. The driver owns two terminal
operations; each Linux lifecycle calls them once on entry and once on exit.
No semantic copy, parser override or editor policy was introduced.

## Actual affected installed acceptance

The sole builder Einstein staged the normal Toad173 + Toad224 integration:

- Toad `9354b391880980c9c987f421e16b9a1fd59b3f3b`
- Core `000a31c562b6d048e26e288b24fcd3f1ac64f803`
- Textual code `4e8d13d21bf98e4ad52e610277d7d06c9035ccfa`
- SDK0.12.1; nativee36 standalone, unchanged.

Candidate package:
`/home/ts/wt/toad-first-ui-end-keypad-20260930/.artifacts/installed-first-ui-end-keypad`.
Raw physical evidence and native editor snapshots:
`/home/ts/.cache/agent-scratch/toad-editor-focus-227-20260930-candidate02`.

The actual installed `toad-comms` launcher ran with this explicit inactive
candidate in isolated st/Xvfb. The 46.042-second continuous journey completed
all seven phase markers. `abcdef` followed by Left, Left, Backspace, Delete,
Right produced **abcf / caret4** in the parent agent editor and the channel
editor. Physical PNGs show the text and no Help panel opening. The same
original parent editor remains after child and channel returns, retaining its
draft: `abcf`, then `abcfabcf`, then `abcfabcfabcf`. Original parent and child
native source/process receipts are byte-equal. Cleanup has zero remaining
owned processes and zero errors. No prompt was submitted; no provider call,
public mutation, input replay or default activation was performed.

**Scoped Delete repair: PASS. Strict whole journey: FAIL retained.**
The physical history click at (750,350) hit an outbound `comms428` link and
opened a legitimate third tab. Its separate native editor accepted the same
keys and held `abcf / caret4`. The script expected that phase to remain in
the parent, so its additive-text and editor-identity assertions failed.
`editing-acceptance.json` is preserved unchanged. This is not evidence of a
focus ownership failure, and the intended pure history-click/PageUp focus
step is **not accepted**. The observed child/parent and channel/parent
returns are accepted. No second capture was used to replace the result.

Candidate01 was rejected before UI launch because its activation metadata
was absent. The builder supplied verified metadata without changing any
source/package byte or private route; that PRE-UI failure is preserved too.

Intermittent Backspace/arrow failure was not reproduced and is not claimed
fixed. Inline and suspend/resume share the corrected native lifecycle but
were not separately exercised physically. This checkpoint is ready only for
the demonstrated Delete boundary; parent owns merge and default activation.

Counterevidence retained: run01 omitted the key script and recorded only
startup/idle; it proves no editing behavior. The corrected run02 supplied
the script and required every physical phase marker.
