# Responsiveness investigation tools

These are the actual profiling, interaction, capture and replay tools used by the
current performance investigation. They are diagnostic tooling, not runtime
features. Start with the [tracking plan](../../docs/audits/ui_responsiveness_plan.md)
and [evidence audit](../../docs/audits/navigation_allocation_20260925.md).

## Environment

Use Python 3.14 and an isolated environment containing Toad's dependencies.
Install `requirements.txt` in the environment used to run these scripts. The
terminal runner also needs Linux, Xvfb, `st`, `xdotool`, and ImageMagick `import`.
It creates its own X display, verifies the target process/window, and refuses an
already-used display. Input automation is confined to that display.

The current implementation also needs the companion Textual performance branch.
See [Textual PR #5](https://github.com/OpenHCSDev/textual/pull/5); the draft's
`pyproject.toml` pins its commit.
Use `PYTHONPATH` to select both source trees, or install their exact commits.
`--dependency-path` can add dependencies from a separate diagnostic environment;
the selected application environment's packages take precedence.

Keep capture output outside the repository (the default is
`~/.cache/toad-performance`) or in ignored `tools/performance/artifacts/`.
Captured real sessions can contain private drafts, messages and paths. Replay
pickles are trusted-local artifacts only, not an interchange format for untrusted
input. No real-session captures are included in this repository.

## Real-terminal fixtures

```sh
python tools/performance/run_isolated.py \
  --source "$TOAD_SOURCE" --framework "$TEXTUAL_SOURCE" \
  --environment "$APP_VENV" --output-dir "$CAPTURES" \
  --name navigation-1 --display :98 --fixture --census
```

The fixture runs real Toad widgets and the persistent renderer, with fixed
read-only native-history responses. It does not contact live owners/providers.
Modes:

| Options | Workload |
| --- | --- |
| default fixture | ten tabs, opens/revisits, toggles, scroll, selection, filters |
| `--open-only` | cold opens plus initial sidebar toggles |
| `--sidebar-only --sidebar-cycles 6` | twelve pointer toggles |
| `--resize-only` | eight native edge drags plus reveal/restore |
| `--resize-sidebars` | add drag-resizing to the full workload |
| `--filters-only --tabs 4` | all seven categories, all-off, rapid bursts, per-thread masks and unsent typing |

`TOAD_REVISIT_SIDEBAR=1` uses native sidebar rows for revisits. Without it the
driver uses the tab strip. The filter fixture contains 720 events covering all
seven semantic categories, rather than toggling absent categories in a
three-kind fixture. It verifies all typed marker characters and restored masks.

`--privileged-display` optionally runs only the owned Xvfb server through
non-interactive sudo (used when a host's `/tmp` lock-file quota prevents ordinary
Xvfb startup). Application/input processes remain unprivileged.

Each capture uses a fresh name and writes manifest, trace, action, state and
screenshot artifacts; optional censuses add JSONL. Manifests include source-file
hashes, observer hash, selected environments and diagnostic policy overrides.

## Textual console and asyncio diagnostics

```sh
python tools/performance/run_devtools.py \
  --source "$TOAD_SOURCE" --framework "$TEXTUAL_SOURCE" \
  --environment "$APP_VENV" --tools-environment "$TOOLS_VENV" \
  --output-dir "$CAPTURES" --display :98
```

This runs the official Textual devtools service on loopback, captures its output,
and adds a 50 ms asyncio slow-callback log. Textual's own handler warning has a
100 ms minimum and measures handler elapsed time, including awaits. Asyncio
diagnostics identify non-yielding task steps. Debug/console runs add overhead and
are not acceptance timing runs.

`check_observer_dispatch.py` verifies that the observer preserves exactly one
dispatch of decorated transcript/ready messages. An earlier observer duplicated
those handlers; the audit explicitly marks affected captures as invalid.

## CPU and allocation profiling

Add `--profile --profile-gil --profile-seconds 40` for py-spy, with
`--py-spy /path/to/py-spy` and `--profile-sudo` if attachment requires it.
GIL-only sample weights are not a wall timeline and cannot be aligned to actions
by summing those weights. Native stack symbolization can be unreliable without
interpreter debug information; Python-only summaries remain available.

For action-scoped Memray:

```sh
python tools/performance/run_isolated.py \
  --framework "$TEXTUAL_SOURCE" --environment "$APP_VENV" \
  --dependency-path "$MEMRAY_SITE_PACKAGES" --output-dir "$CAPTURES" \
  --name allocations-1 --display :98 --fixture --sidebar-only \
  --sidebar-cycles 2 --focused-profile memray
```

The observer starts/stops capture through an owned signal/receipt handshake.
Geometry snapshots and pointer positioning are outside each action's capture.
Memray uses aggregated allocation records: use `analyze_focused.py` for peak/end
allocation stacks; `memray stats` does not support that format. End allocations
are not automatically leaks. `--focused-profile cprofile` is also available, but
the audit records suspicious caller attribution in a whole-interval CPython
3.14.2 experiment; do not use it as standalone causal proof.

Optional source-backed probes:

- `TOAD_VALIDATION_LAYOUT_CAUSES=1`: record new layout invalidation callers.
- `TOAD_VALIDATION_OPEN_STAGES=1`: construction/mount and navigation-stage spans.
- `TOAD_VALIDATION_LEGACY_MARKDOWN_MEASUREMENT=1`: explicit diagnostic control for
  the default Markdown virtual-size feedback policy.
- `TOAD_VALIDATION_UNGATED_STARTUP=1`: after-refresh rather than actual-first-frame
  startup control. This is not an exact historical-source checkout.
- `benchmark_dom_storage.py`: bounded tracemalloc construction fixture; not FPS.
- `benchmark_spinner.py --fps 60 --seconds 3`: native headless spinner/compositor
  timing with layout/CSS counters. This is component frame work, not terminal FPS
  and not proof of the budget under a large captured workload.

## User-authorized live capture

```sh
python tools/performance/capture_live.py --pid "$TOAD_PID" \
  --output-dir "$CAPTURES" --name aged-live-1 \
  --profile-seconds 45 --gil --state --screen --sudo
```

The PID is explicit and identity-checked. Sampling runs before state capture.
State/SVG capture uses CPython 3.14 `sys.remote_exec`, executes a one-shot reader
at the target's normal interpreter boundary, and invokes Textual's screenshot
API. It does not send UI input, restart the app, or issue owner RPCs. Capture does
allocate/read data and screenshot export performs a full render, so it is not a
zero-overhead measurement interval.

`capture_state.py` saves a versioned DTO bundle plus metadata: open modes,
filters, loaded pages, draft data, cached sidebar projection, direct-content
records where available, and retained closed-reactive-subscription paths.
Serialization runs on a background thread. Files are created with mode0600.
This is not a checkpoint of sockets, workers, or the entire Python heap.

`capture_window.py --window XID --output FILE.png` is an optional read-only X11
pixel capture. Unmapped windows may reject XGetImage; the Textual SVG path works
without moving or focusing the user's window.

## Headless captured-data replay

```sh
PYTHONPATH="$TOAD_SOURCE/src:$TEXTUAL_SOURCE/src" "$APP_VENV/bin/python" \
  tools/performance/replay_state.py \
  --bundle "$CAPTURES/aged-live-1-state.pickle" \
  --output "$CAPTURES/replay-1.json"
```

Replay creates a private temporary wire/config/store, reconstructs native and
channel views, restores captured filters/drafts/placement where available, and
exercises filters while typing. It does not clone executor ownership, contact
the original wire, or start providers. The earlier v3 capture/replay is a bounded
loaded-text/page representation: transient tool widgets and some live input
metadata were not fully captured. Later capture code also records direct
contents, but the legacy replay projection remains partial and explicitly so.

`--legacy-watches` disables the new subscription teardown in the replay only for
an ownership control. Headless `settled_ms` includes pilot settlement and must
not be presented as terminal/pixel latency. The reports separately include
synchronous filter-setter CPU/wall time and closed-subscriber counts.

## Analysis and checks

All analysis commands take full capture prefixes or files, not machine-specific
cache names:

- `analyze_trace.py PREFIX`: loop/GC/layout/render and slow-gap attribution.
- `analyze_filters.py PREFIX...`: category coverage, drafts and key acknowledgment.
- `summarize_opening.py PREFIX...`: click-to-target flush / ready completion;
  excludes no-op same-tab clicks.
- `analyze_navigation.py PREFIX`, `analyze_cold_open.py PREFIX [COUNT]`,
  `analyze_open_layouts.py PREFIX`: stage and layout breakdowns.
- `summarize_sidebar.py PREFIX...`, `compare_sidebar.py PREFIX...`,
  `analyze_layout_causes.py PREFIX`: toggle/drag and invalidation work.
- `summarize_profile.py FILE [--thread NAME]`: bounded sampled stack summaries.
- `analyze_focused.py FILE`: Memray or cProfile reports.
- `inspect_replay.py BUNDLE`, `compare_replays.py FILE...`: saved-data summaries.
- `check_receipts.py PREFIX... [--same-code]`: source/action/code comparability.
- `python -m pytest tools/performance/test_pilots.py -q -n 2`: subprocess pilots.
  Set `TOAD_TEST_PYTHON` for a separate application interpreter.

The pilot wrapper uses file-backed output capture: a persistent descendant can
keep a PIPE open after the tested process exits. This preserves bounded process
completion and failure logs without confusing pipe EOF with application exit.

Heartbeat gaps, handler elapsed time, UI-thread CPU, headless settlement, terminal
flush and physical pixels are distinct measurements. Inclusive spans overlap.
Do not hide maxima, GC outliers, source changes, profiler overhead or resource
contention behind a passing action count.
