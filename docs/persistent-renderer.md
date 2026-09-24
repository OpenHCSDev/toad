# Persistent renderer checkpoint

The OpenHCSDev fork offers a POSIX-only, opt-in persistent CPU renderer. It uses
ZMQRuntime's ordinary IPC endpoint lifecycle, a nominal `Renderer` ABC and typed
render tasks and commands. Diff preparation and large transcript fragmentation
run in CPU workers. Prepared Markdown parsing/highlighting additionally requires
the paired OpenHCSDev Textual hooks; stock Textual retains native Markdown parsing.

The default **local** renderer also uses CPU worker processes. File previews and
the shared `WorkerStatic` component use those workers automatically; selecting
the persistent backend changes worker lifetime/reuse, not whether previews are
prepared off the UI thread.

## Try it

In an environment with this fork's compatible dependencies:

```sh
python -m pip install -e '.[persistent-renderer]'
toad run --renderer persistent /path/to/project
# Or select the renderer for an existing ACP launcher:
TOAD_RENDERER=persistent toad acp 'python -m agent_comms.acp' /path/to/project --session THREAD
```

Use `--renderer local` or unset `TOAD_RENDERER` to retain app-local workers.
`ToadApp(renderer=...)` also accepts an explicit `Renderer` instance, which the app
closes on unmount. Construction starts no service. After the first completed UI
display, the app schedules the renderer's optional `warm_up` hook. The persistent
backend uses small Markdown/Python/JSON and diff tasks to prepare worker imports;
fingerprinting, connection and preparation run off the UI loop. Local workers
retain their lazy behavior. Typing and navigation do not await warm-up.

For reproducible installed dependencies, use the agent-comms stack's checked-in
manifest and lock. The original pre-merge dependency-gate notes are historical;
the measurements below retain their stated source-checkpoint scope.

## Worker-backed Rich views

Use the shared component for data-only Rich output instead of creating an
executor/adapter in each view:

```python
from toad.widgets.worker_static import WorkerStatic

code_view = WorkerStatic.code(source, filename="module.py")
rich_view = WorkerStatic(rich_table)
rich_view.update(updated_rich_table)
```

The common `RichRenderTask` performs materialization, lexer discovery,
measurement, highlighting and Rich segmentation through the app-owned renderer.
The UI measures prepared dimensions and paints only requested rows; selection
and copy preserve displayed text. Picklable Rich renderables work directly.
`RichSource` is the nominal data-only construction interface when construction
itself is expensive (the built-in `SyntaxSource` implements code previews).
Widgets, apps and core services are not renderable payloads.

Source/style/width updates coalesce behind one per-widget in-flight preparation;
stale or closed-view results are discarded. File reading runs after the preview
tab mounts, so IO and preparation waits allow typing and navigation. Markdown
previews use the existing shared prepared Markdown path. Existing file byte
limits and binary/error handling remain in effect.

An 84,027-byte Python-file fixture measured the old native path against the
worker-backed component in one app. Maximum event-loop gaps were 1,561–1,687ms
before and 15.83–16.35ms after. Opening-handler time was 1,703–1,725ms before and
32.69–33.97ms after; worker content became ready in 1,139ms cold / 705ms warm.
These are two bounded headless observations, not terminal-pixel acceptance.

## Lifetime and failure semantics

- The service persists after a client window closes; compatible later windows
  reuse it. Default capacity is two CPU workers and four retained/active jobs.
- Source content, editable renderer dependencies, interpreter and service config
  identify each build. Distinct builds use distinct private IPC directories under
  the platform's `toad-renderer` runtime directory. The server and lazily spawned
  workers check their build before accepting work.
- Each client owns its requests. Cancellation does not release a running slot
  before work finishes. Completed results stay until acknowledged; disconnected
  clients' leases expire so abandoned results can be reclaimed.
- Auto-expanded diffs in hidden open views prepare data before viewport activation.
  A typed per-source/theme future lets the visible view consume the same completed
  or in-flight work. One app-owned background admission remains occupied until
  actual completion, including when its widget waiter is cancelled; stale source
  and theme generations cannot publish. Rich widgets remain viewport-bounded.
- Inactive open channel/DM views prefetch a bounded history page through a shared
  I/O reader. Only one hidden read runs at a time; foreground reads do not queue
  behind unrelated inactive tabs. A ready or in-flight matching page is reused
  on activation. Prefetch does not mount messages or acknowledge read markers.
  Revision, route, cursor and follow intent identify prepared data, so changes
  invalidate stale results. Watermark/page reads run off the UI loop.
- A failed RPC ends that client session. The application adapter drains/releases
  it before later requests create a new client. Failed requests are reported and
  are not silently replayed. Existing failed widgets do not automatically retry.
- `PersistentRendererPool.shutdown_service()` is the explicit async owner/test
  shutdown API. Normal `aclose()` leaves the service running. Automatic retirement
  of older-build services and byte-based memory bounds remain future work.

## Verification checkpoint

Run pilots with the intended Toad and Textual source directories first on
`PYTHONPATH`; child processes must import those same sources. The persistent pilots
also need the optional extra. They create disposable endpoints and shut them down.

```sh
python tests/render_identity_pilot.py
python tests/render_service_pilot.py
python tests/persistent_renderer_lifecycle_pilot.py
python tests/render_runtime_pilot.py
python tests/renderer_warmup_pilot.py
python tests/hidden_diff_warmup_pilot.py
python tests/channel_history_reader_pilot.py
python tests/channel_background_warmup_pilot.py
python tests/renderer_selection_pilot.py
python tests/persistent_render_pilot.py
python tests/persistent_renderer_ui_pilot.py
python tests/worker_preview_pilot.py
python tests/file_preview_latency_pilot.py
```

The real UI pilot creates two Toad instances using the supported constructor,
verifies warm-up succeeds, renders Markdown, a native tool diff and a file preview, and checks
reuse of the same service. The warm-up lifecycle pilot holds preparation behind
a gate and verifies typing, tab navigation, drafts and shutdown still work.
Existing process/transcript, Markdown lifecycle/row parity, diff lifecycle/style,
retained text and footer pilots are the compatibility checks for this checkpoint.

A manual desktop test was reported as “working pretty good.” A separate bounded
headless fixture (35 KB Markdown, 1,200 code lines) observed first completed updates
of 647–656 ms with new app-local workers, 454 ms with a reused persistent service,
and 1,409 ms starting that service cold. These are individual observations, not
terminal-pixel latency measurements. UI-loop pauses remained 45–57 ms. Cold startup,
Channels/tab loading and the separate <16 ms presentation target remain open.
