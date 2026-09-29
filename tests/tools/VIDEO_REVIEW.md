# Installed TUI video assessment

Use `record_installed_tui.py` for visible startup, tab return, sidebar, scrolling,
fork, notification and status defects. It launches **`st -e toad-comms`** on its
own Xvfb display. Every mouse/key command receives that isolated `DISPLAY`;
the owner's desktop, pointer and existing Toad process are untouched. The actual
application, installed packages, saved history and ACP are used.

The recorder uses stdlib Python plus Xvfb, st, xdotool, ffmpeg and ImageMagick
`import`. Run the existing resource guard first. Keep runs serial and bounded;
the encoder has one thread. Output stays in a named persistent scratch directory.
Recorded user history stays local; commit tools and controlled fixture evidence.

## Record a real journey

Take a screenshot first to locate the controls in this terminal geometry. Supply
a native xdotool script; do not assume another machine's pixel coordinates. This
example opens two sidebar threads, lets their first histories load, then clicks
the actual tabs A/B/A. Replace its coordinates using the captured `before.png`.

```text
mousemove --sync 130 200
click 1
sleep 4
mousemove --sync 130 280
click 1
sleep 4
mousemove --sync 350 40
click 1
sleep 1
mousemove --sync 520 40
click 1
sleep 1
mousemove --sync 350 40
click 1
sleep 1
```

```sh
python tests/tools/record_installed_tui.py \
  --fit-window --actions /home/ts/.cache/agent-scratch/tab-return.xdo \
  --review-start 16 --review-seconds 3 --review-fps 8 \
  -- toad-comms
```

Without `--actions`, it records startup until `--max-duration`. To test a staged
candidate, select its reviewed runtime via `AGENT_COMMS_RUNTIME_ROOT` before
launching the same tool. The recorder inherits runtime selection and records the
command. Confirm which runtime was selected; default activation metadata alone
does not establish a candidate version. `NO_COLOR` is removed from the child
environment because tool shells can inherit it and hide the UI's colored text.
No global environment or installed package is changed.

Artifacts are `terminal.mp4` at the capture frame rate, `slow.mp4` for the chosen
interval, timestamped `frames.png`, before/after screenshots, the exact driver
script, process logs and `receipt.json`. FPS, playback speed, review interval,
frame sampling and terminal size are parameters. Capture at high FPS and slow
playback afterward so short blank/rebuild frames are preserved. A new output
directory is required so interrupted-run evidence is not overwritten.

## Assess before calling a UI fix ready

1. Inspect `before.png` and runtime selection. Verify representative retained
   history, actual destination tabs and the affected opening path are present.
2. Watch normal-speed video and slowed playback around every cold and warm click.
   Inspect the frame sheet, and extract additional full-resolution frames for
   an ambiguous interval. Inspect the actual saved video, not just a widget
   identity or a compositor method's return value.
3. On A/B/A returns, verify the first visible destination frame has the expected
   reader position and rendered content. Reject visible empty/loading intervals,
   text appearing in batches, reader jumps, wrong-thread content, stale status
   or goal, and duplicate temporary/replacement tabs. A correct final screenshot
   does not excuse incorrect intermediate frames.
4. For scrolling, include fast, reverse, idle and End interactions. Check visible
   preparation gaps and scrolling into empty space. For message/status work,
   use the existing owned native/ACP controlled-provider fixture to cover a real
   stream and settlement; do not resend uncertain user inputs to get a recording.
5. Compare the same journey on the failing installation and candidate with the
   same viewport/state. Correlate video intervals with existing phase timings,
   preparation hits and renderer submissions. A hit count proves reuse at that
   layer, not visually warm tab return.
6. Report the observed frames, version, path and limits in the PR. A recorder exit
   of zero means **capture completed**; `assessment` starts as `unreviewed`.
   Review the artifacts before recording a separate pass/fail assessment with
   time intervals and supporting frame paths. Preserve a demonstrated failing
   capture and use it to strengthen the continuous journey's regression checks.

Clean owned recordings after the relevant fix/evidence is durable. Never delete
native saved sessions, the active bus, worktrees or other agents' outputs as part
of recorder cleanup. The tool stops only the processes it created.
