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
a speed improvement over PR200. The actual large saved-history `st -e
toad-comms` recording, including held PageUp/PageDown/reverse/End/idle, remains
the acceptance boundary. The parent owns installed runtime activation; Mendel
owns the isolated physical-key recording tools.
