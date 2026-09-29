# Installed TUI video assessment

`record_installed_tui.py` launches plain **`st -e toad-comms [THREAD]`** on a
new Xvfb display with an unused number above 99. It uses the installed application, saved history, native ACP
and real mouse/keyboard events. It refuses display zero and passes its isolated
`DISPLAY` to every driver and screenshot process. Run only trusted native
xdotool scripts; never override `DISPLAY` inside a script.

Prerequisites: Python 3.14, Xvfb, st, xdotool, ffmpeg/ffprobe and ImageMagick
`import`. Run `/home/ts/bin/agent-resource-check --assert-headroom` first and
keep captures serial. Capture and review encoders/filters use one thread.
Capture is capped at 120 seconds, 1920×1200 and 120 FPS; sheets at 96 frames
and 24 million pixels. Each subprocess has a timeout. Output must be a fresh
directory under `~/.cache/agent-scratch`; record its owner and retention purpose.
Recorded user history stays local.

## Record startup and physical tab return

Locate controls in `before.png` or an existing capture of the same geometry.
Use `--fit-window` for a 1260×780 terminal on the default 1280×800 screen.
A native stdin script opens saved sources and physically clicks A/B/A:

```text
mousemove --sync 130 240
click 1
sleep 4
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark opened-a
mousemove --sync 130 200
click 1
sleep 4
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark opened-b
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-a
mousemove --sync 220 40
click 1
sleep 1
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-b
mousemove --sync 350 40
click 1
sleep 1
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-return
mousemove --sync 220 40
click 1
sleep 1
```

Replace coordinates with actual tab/sidebar locations. In the inspected two-tab
installation these tab centers were 220,40 and 350,40; 520,40 hit empty tab-bar
space. Sidebar order can change after opening a source. Marks **before** a click
include its first destination frames in that review interval. Marks timestamp
command boundaries, not application paint acknowledgements. Replace `/ABS/PATH`
with this checkout's absolute path. The generated script writes literal quoted
Python/tool paths. Native xdotool stdin environment expansion can swallow
following arguments when expanding paths, so avoid it here. No shell evaluates
the script.

```sh
python tests/tools/record_installed_tui.py \
  --owner YOUR-NAME --fit-window --startup-wait 15 --max-duration 70 \
  --actions /home/ts/.cache/agent-scratch/YOUR-RUN/journey.xdo \
  --review-start 0 --review-seconds 3 \
  --review-phase warm-a --review-phase warm-b --review-phase warm-return \
  --output /home/ts/.cache/agent-scratch/YOUR-RUN/recording \
  -- toad-comms
```

Without actions it records startup within the capture budget. A zero exit means
capture, artifacts and cleanup completed. `assessment` always starts
**`unreviewed`**; it never certifies a UI fix.

## Held scrolling, reversal, End and idle

Generate an editable native script, then append it to the opening/tab script:

```sh
python tests/tools/record_installed_tui.py --write-scroll-script \
  /home/ts/.cache/agent-scratch/YOUR-RUN/scroll.xdo
```

The generated script physically clicks the message area at `700,260`, captures
`focused`, and runs this sequence with timestamp/screenshot markers around each
phase:

```text
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark up
keydown Prior
sleep 4
keyup Prior
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark up-done
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark down
keydown Next
sleep 4
keyup Next
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark down-done
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark reverse
keydown Prior
sleep 4
keyup Prior
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark reverse-done
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark end
key End
sleep 1
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark idle
sleep 4
exec --sync /usr/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark idle-done
```

Choose a visible message body, avoiding links, tools, disclosures and the editor.
**Verify focus from the actual result:** `phase-focused.png`, `phase-up-done.png`
and `phase-down-done.png` must show history moving through multiple pages in the
expected direction. Held keys reaching the editor or a non-scrollable child do
not establish coverage. Adjust the physical click and repeat only navigation.
No scroll setter, copied application state or substitute UI is used.

Add `--review-phase up --review-phase down --review-phase reverse
--review-phase end --review-phase idle` to the capture command. Up to eight
named intervals are supported. Use `--review-seconds 5 --review-frames 40` to
cover a whole four-second hold plus its boundary; the default three-second
review samples the beginning. Inspect the remaining hold from the normal video
as well. End must reach the destination bottom, followed by a stationary pause.
Do not accept empty space beyond the bottom, reflow, blanking or repeated
history rebuilding. Background preparation counters alone cannot show that
renderers prevented a visible hiccup; compare actual frames and the performance
owner's preparation evidence.

## Runtime provenance and artifacts

`AGENT_COMMS_RUNTIME_ROOT` selects a reviewed candidate **bin directory** holding
`python` and `toad`. Otherwise selection follows `AGENT_COMMS_ACP_LAUNCHER`, then
the installed ACP launcher on PATH. Selection is pinned for this run. No global
packages, launcher links, owner processes or environment are changed.

`receipt.json` records the selected launcher/hash, bin directory, its activation
path/content/hash if present, and an independent probe through the selected
Python before and after capture. The probe records interpreter/prefix, package
origins, versions, distribution direct URLs and source-tree hashes for Toad,
Textual and core. Activation metadata is a claim; package origins and hashes
identify the observed bytes. A candidate without activation metadata still has
observed provenance; never attribute the default activation SHA to it. Missing
metadata cannot establish a reviewed Git SHA. Compare the performance owner's
wheel/source receipt to the observed candidate before assessing it.

Outputs include the full 60 FPS `terminal.mp4`, default 8× `slow.mp4`, timestamped
`frames.png`, `before.png`, `after.png`, the exact action script, logs and receipt.
Each named phase adds `LABEL-slow.mp4` and `LABEL-frames.png`. Native marks append
`events.jsonl` and `phase-LABEL.png`. The receipt includes intervals, media probe,
artifact hashes, runtime comparison and process cleanup. Frame-sheet labels add
the seek offset and refer to **source-video seconds**. Native event times are
monotonic seconds since encoder launch; encoder startup can introduce a small
offset, so correlate key effects against the saved video.

SIGINT/SIGTERM/SIGHUP and timed-out commands clean owned sessions/descendants,
including native children that changed process groups, using PID/start ticks.
ffmpeg may return 255 after the requested SIGINT; media probing and nonempty
artifacts are still required. Interrupted evidence receives an error receipt.
Review subprocesses are bounded and are stopped on timeout. SIGKILL or host
failure cannot run Python cleanup; inspect the recorded owned identities before
cleaning such an interrupted run. Never stop an existing attached owner.

## Assess the visible behavior

1. Verify readable saved history, actual destination sources and keyboard focus.
2. Inspect the normal video, slow intervals and contact sheets around every cold
   open, warm return, held scroll/reversal, End and idle. Extract full-resolution
   60 FPS frames when a sampled sheet leaves ambiguity.
3. Reject empty/loading destination frames, text appearing in batches, reader
   jumps, wrong-thread content, stale state, duplicate tabs, blanking, reflow,
   preparation gaps and void past the end. A correct final screenshot does not
   excuse intermediate defects.
4. Compare failing and candidate runs with the same viewport/history and exact
   candidate provenance. Coordinate findings with the performance owner. Keep
   preparation hits, renderer reuse, first-frame latency and visible quality as
   distinct observations. The recorder does not measure background work itself.
5. Write a separate local `assessment.json` with reviewed intervals, supporting
   frames, findings and explicit limits. Do not change capture `assessment` into
   an automatic pass. For message/stream/status work, use the existing owned
   native/ACP controlled-provider fixture; never resend uncertain user input.

Retain demonstrated failures until their fix/evidence is durable. Delete owned
failed recordings and disposable probes after extracting useful receipts; keep
review evidence until its follow-up is accepted. Never delete saved sessions,
the active bus, worktrees or another agent's evidence.
