# Retained outer history candidate

This draft extends the existing viewport working set to retain a mounted
`TranscriptHistory` in its session slot. On return, the same outer history,
pages, and response widgets are reparented into the selected Contents before
the native journal is validated after first display. Parked descendants leave
active viewport admission and rejoin it on return. The existing preparation
runtime and worker backed `RenderPreparation` remain the render owners.

## Source and protocol pilot

The controlled provider native Pi/ACP journey used the copied configured Pi
package, paired Textual runtime, two produced journals, actual tab clicks, and
five A/B/A returns. It passed source, goal, turn, draft/undo, scroll position,
no replay, bounded preparation, and mounted outer history/page/response identity
assertions. All five returns had zero preparation misses and no blank, loading,
or wrong-source completed frames. The receipt and run log are in
`/home/ts/.cache/agent-scratch/toad-retained-outer-history-first-paint-20260929/native-outer-final.json`
and `native-outer-final.log` in that directory.

Command, from this worktree:

```sh
timeout --signal=TERM --kill-after=10s 180s env PYTHONPATH=src:tests TMPDIR=/home/ts/.cache/agent-scratch/toad-retained-outer-history-first-paint-20260929/tmp AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-9213ee71479d1b20/node_modules/@earendil-works/pi-coding-agent NATIVE_RETURN_RECEIPT=/home/ts/.cache/agent-scratch/toad-retained-outer-history-first-paint-20260929/native-outer-final.json /home/ts/.local/share/agent-comms/runtime-turn-authority-20260929/bin/python -u tests/native_loaded_return_cache_pilot.py
```

Median selection to first completed display was 244.5 ms (five returns). The
first completed destination frame still changes from reader length 2516 or
2517 at maximum scroll 42 to 2368 at maximum scroll 43 in later completed
frames. This source pilot does **not** establish visually stable first paint or
a speed improvement over PR200.

## Installed large-history video

Mendel's isolated Xvfb/st recording used an installed wheel from this draft,
Core406 and Textual412. It exercised physical A/B/A tab clicks and held
PageUp/PageDown/reverse/End/idle on the actual saved live history. The
profiled and unprofiled videos and monotonic event/CPU receipts are under
`/home/ts/.cache/agent-scratch/toad-video-tools-mendel-20260929/candidate-profiled`
and `candidate-unprofiled` there. On warm return, the destination tab became
selected while the previous source's body remained visible for several frames;
the destination history then filled and shifted across later frames. This
**fails visual warm-return acceptance**, despite the source pilot's widget
identity and final-frame assertions. The unprofiled control is invalid:
`nra-architecture` attachment failed before its warm-return frames. The
sampled UI profile has many sample errors and is only partial attribution,
not a measured speedup or a complete CPU breakdown.
The same profiled video/CPU receipt measured the UI process at 58.3% average
CPU during warm A, 73.4% during warm B, 97.2% during held PageUp, 97.1%
during reverse PageUp, and 53.6% during idle; measured preparation worker
processes were near zero in those intervals. These are phase-wide process
counter deltas, not per-frame execution time. The py-spy trace had 407 errors
in 500 sampling attempts, so its named call stacks are only leads.

The recorder invoked `st -e toad-comms` with `AGENT_COMMS_RUNTIME_ROOT` set to
the isolated candidate runtime. The launcher clears private root/native pins,
resolves the project on the active route and starts candidate ACP. This can
reach live owner attachment during tab clicks. After a live owner attachment
failure and native-pin mismatch were reported, further live-root candidate
captures were stopped. One owner PID appeared in the recorder's descendant
cleanup identities; the cleanup may have stopped an owner it launched. This
remains under parent-owned incident review. Resume recording only against an
approved default ACP or an explicitly complete, matched private root/native environment. The
parent owns live-route recovery and installed runtime activation; Mendel owns
the isolated physical-key recording tools.

## Paired private candidate

The exact `5732952d81b0103507bdb17123d25d62a0891934` wheel is installed
only in `/home/ts/.cache/agent-scratch/toad-retained-outer-history-first-paint-20260929/installed-runtime`.
Its activation receipt pins Core `fc47c15a`, Textual `412b5a2b` and native
package `776dc368`. The wheel SHA-256 is
`4ba3c73065814c11231fdbb540a5f50fce6570f5dec7ffa82171aeba955dbf31`;
all 297 `toad/` files matched both the worktree source and the isolated
installation byte for byte. The private physical capture must launch that
runtime's `toad acp` and Python directly with the fixture's matching root ID
and native package pins. The `toad-comms` wrapper clears those pins and is
therefore unsuitable for this candidate capture.

The exact wheel's subsequent matched-private recordings are in Mendel's
`candidate-private-custody/private-profiled` and `private-unprofiled` directories.
Both show the previous response number under the selected destination tab
for several reviewed frames. Physical PageUp/PageDown changes actual native
history, but End leaves earlier paragraphs and the Jump to Latest control
visible during idle. Neither recording passes visual acceptance.
The profiled run measured 85.1% UI CPU during PageUp, 83.3% during reverse,
and 29.6% during idle. Its sampler reported 368 errors in 369 samples;
call-stack attribution is insufficient to assign those costs precisely.

After the server interruption, Mendel inspected the original private owners
and input dispositions, verified a uniquely new controlled input once through
actual ACP, and stopped only those private fixture owners through Core's
lifecycle. `custody-resume-acceptance.json` records successful attachment,
one loopback provider request, and no replay. This custody result is separate
from the failed visual assessment. No interrupted test is being replayed.

## Remaining style and layout cost

Textual412's `Widget.reparent()` calls `stylesheet.update_nodes()` over every
descendant and refreshes layout on both old and new parents. This draft parks
and reclaims the full mounted history through `reparent()`. Preserved fragment
and widget render caches therefore do not imply preserved layout or a warm
terminal Strip frame. The source pilot measured a median 244.5 ms from
selection to first completed display, with `native_activate` around 124–150 ms
and destination `layout_navigation` around 20–24 ms across its five returns.
The reparent traversal is a likely contributor, not isolated by that timing.
