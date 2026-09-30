# Installed TUI video assessment

`record_installed_tui.py` launches plain **st** with the installed **Toad ACP
entrypoint** on a new isolated Xvfb display above 99. Capture now requires an
existing private native fixture with explicit root, wire-root ID and native
package pins. It refuses the owner's active route. The `toad-comms` wrapper
clears private pins, so it is refused for capture. No global runtime changes
are needed. Actual saved state, UI, ACP and native processing remain intact.

Run the recorder with the selected installed runtime's Python. Reuse
`tests/l0a_native_installed_pilot.py` and its saved-state preparation callback:
its loopback provider is bounded and never reaches a paid service. Fixture
setup owns the native processes; the recorder only attaches. Configuration,
projects, saved-session evidence and video belong under named persistent agent
scratch. Current Core's `nk_foreground` requires a disposable private `/var/tmp`
wire root; preserve its generated evidence into scratch before fixture teardown.
Do not redirect the owner's route or alter that Core guard.

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
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark opened-a
mousemove --sync 130 200
click 1
sleep 4
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark opened-b
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-a
mousemove --sync 220 40
click 1
sleep 1
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-b
mousemove --sync 350 40
click 1
sleep 1
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark warm-return
mousemove --sync 220 40
click 1
sleep 1
```

Replace coordinates with actual tab/sidebar locations. In the inspected two-tab
installation these tab centers were 220,40 and 350,40; 520,40 hit empty tab-bar
space. Sidebar order can change after opening a source. Marks **before** a click
include its first destination frames in that review interval. Marks timestamp
command boundaries, not application paint acknowledgements. Replace `/ABS/PATH`
with this checkout's absolute path, and `/ABS/RUNTIME/bin/python` with the selected installed interpreter. The generated script writes literal quoted
Python/tool paths. Native xdotool stdin environment expansion can swallow
following arguments when expanding paths, so avoid it here. No shell evaluates
the script.

```sh
"$candidate_python" tests/tools/record_installed_tui.py \
  --private-root "$fixture_root" --owner YOUR-NAME --fit-window --startup-wait 15 --max-duration 70 \
  --actions /home/ts/.cache/agent-scratch/YOUR-RUN/journey.xdo \
  --review-start 0 --review-seconds 3 \
  --review-phase warm-a --review-phase warm-b --review-phase warm-return \
  --output /home/ts/.cache/agent-scratch/YOUR-RUN/recording \
  -- "$candidate_toad" acp "$candidate_python -m agent_comms.acp" \
  "$fixture_project" --session beta
```

The fixture must already export `AGENT_COMMS_ROOT`,
`AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID` and
`AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE`. Set `AGENT_COMMS_RUNTIME_ROOT` to the
candidate's bin directory; the selected interpreter and ACP command must match.
These are fixture values, never the owner's active root. Shell variables above
are task-specific paths from that existing fixture. Without actions it records
startup within the capture budget. A zero exit means
capture, artifacts and cleanup completed. `assessment` always starts
**`unreviewed`**; it never certifies a UI fix.

## Held scrolling, reversal, End and idle

Generate an editable native script, then append it to the opening/tab script:

```sh
"$candidate_python" tests/tools/record_installed_tui.py --write-scroll-script \
  /home/ts/.cache/agent-scratch/YOUR-RUN/scroll.xdo
```

The generated script physically clicks the message area at `700,260`, captures
`focused`, and runs this sequence with timestamp/screenshot markers around each
phase:

```text
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark up
keydown Prior
sleep 4
keyup Prior
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark up-done
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark down
keydown Next
sleep 4
keyup Next
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark down-done
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark reverse
keydown Prior
sleep 4
keyup Prior
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark reverse-done
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark end
key End
sleep 1
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark idle
sleep 4
exec --sync /ABS/RUNTIME/bin/python /ABS/PATH/tests/tools/record_installed_tui.py --mark idle-done
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

`--profile` uses consistent stack reads by default. `--profile-sampling
nonblocking` selects py-spy's nonblocking reads explicitly. The actual policy
is recorded with the launch command and profile review. Consistent sampling
briefly pauses Python; nonblocking sampling can read an inconsistent stack.
Inspect reported sampling errors and missing intervals, and compare a short
unprofiled capture of the same actions before attributing a visible delay.
Neither a profiler exit code nor a sparse profile establishes correctness.

`AGENT_COMMS_RUNTIME_ROOT` selects a reviewed candidate **bin directory** holding
`python` and `toad`. Otherwise selection follows `AGENT_COMMS_ACP_LAUNCHER`, then
the installed ACP launcher on PATH. Selection is pinned for this run. The actual private route and native package
are independently observed through Core authorities and matched to activation.
No global packages or launcher links are changed.

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

Cleanup uses installed `agent_comms.child_process` **ParentedProcess** custody,
**Platform** process groups and identity-bound pidfd signaling. It never adopts
arbitrary descendants or detached service sessions. The real **Registration** snapshot
also excludes durable comms owners by their declared process identities. The
terminal's one direct `-e` program starts a separate session: its exact launch
identity is transferred to **ObservedProcess** and its executable is verified
against the selected interpreter. Failed verification still cleans that launch.
The profiler wrapper publishes its st identity before Core releases the exec
gate, then atomically publishes the program identity in `profile-terminal.json`.
The parent recovers both on timeout or profiler failure. Transferred custody
cannot claim a parent's reap result. `ui_identity` and `terminal_processes` include
the verified UI session and its group. Background service lifetimes remain
with their existing owners. No command-name heuristics or copied PID registry
establish stop authority.

SIGINT/SIGTERM/SIGHUP and command timeouts clean the capture's groups. ffmpeg may
return 255 after requested SIGINT; media probing and nonempty artifacts are
required. SIGKILL or host failure cannot execute cleanup. The receipt records
capture custody identities and cleanup errors; inspect those identities before
cleaning an interrupted run. The fixture separately checks that its original
owners survive capture, remain attachable and process a new controlled input,
then uses its own lifecycle teardown. No production owner is restarted.

The owned acceptance probes in `evidence/installed-tui-video` extend the existing
native fixture; their multiprocessing entry guards are required. The separate
terminal custody probe covers abrupt terminal/profiler exit and failed runtime
verification. Its sleeping OS programs establish cleanup only; real UI acceptance
comes from the private installed journey. After a host/server interruption, inspect
saved identities and input dispositions before any new action. A resume check must
attach the original surviving owners and send a uniquely new loopback input only
after excluding UNKNOWN or already attempted input. Preserve its receipt separately
from the interrupted run; never infer continuity or replay an uncertain attempt.

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

## Same-run UI and renderer CPU profile

Add `--profile --profile-rate 25` to the same physical journey. This uses the
installed **py-spy**, the selected stack-read policy and its existing Chrome trace format;
Python renderer subprocesses are included. A small recorder wrapper
launches plain `st -e <installed toad> acp ...`, waits for its actual Python UI PID and then
executes py-spy as that UI process's ancestor under Linux `ptrace_scope=1`.
Application, protocol and
saved state follow the installed entrypoint. It neither imports a substitute app
nor installs packages or changes ptrace policy. Profiling is optional and bounded
at 10–49 Hz and capture duration plus 30 seconds. Review refuses raw traces larger than 128 MiB.
A trace missing the verified main UI PID is rejected; sampling a launcher or
workers alone does not establish UI stack coverage.

Native action marks also read cumulative kernel CPU counters for the actual
terminal/UI and current renderer descendants. `events.jsonl` includes monotonic
video offsets, PID/start identities and CPU seconds. No polling monitor or
application state store is introduced. CPU snapshots are included in unprofiled
marks too, so the comparison uses the same action-boundary instrumentation. `cpu-profile.json` is the raw py-spy
trace; `profile-review.json` maps action/video intervals to measured per-process
CPU deltas and hot sampled functions. Background worker identities and stacks
are included when py-spy sees them. The summary records py-spy sample/error
counts and marks attribution partial when errors occur. Idle or exited threads
can retain long Chrome stack spans; do not assign those spans CPU cost when
the kernel counters show no CPU change. Self and inclusive sampled wall spans
are both retained, with self spans used for ranking. Sampled activation, preparation, layout and
paint functions provide phase activity; existing pilot instrumentation has no
production enable flag, so these are not exact phase entry/exit events.

The wrapper records its monotonic profiler-exec boundary, and the recorder
records observation of py-spy's sampling-ready message. Those bounds align the
trace's relative clock with the video origin. Alignment uses their midpoint,
with half the bound width plus one sample period as nominal uncertainty;
scheduler delay or sampler errors can increase it. Keep the raw clocks/trace,
profiler log and this uncertainty in every correlation report. Nested sampled stack spans are
inclusive wall activity, not exact call counts, per-function CPU attribution or
proof of redundant work. The kernel deltas are the measured CPU totals.

Run a short **unprofiled** comparison serially with the same runtime, viewport,
history sources and physical actions. Mark it separately in the assessment and
compare the visible switch/scroll/End behavior. Record perturbation and changes
in timing; never subtract an assumed profiler overhead or certify a candidate
from the profiled run alone. Associate inspected stall frame intervals with the
matching `profile-review.json` phase and supporting sampled stacks in the local
`assessment.json`. Leave absent/unsampled phases explicit. The performance owner
must decide whether sampled work is redundant and implement its fix.
