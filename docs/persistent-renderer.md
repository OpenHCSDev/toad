# Persistent renderer checkpoint

The OpenHCSDev fork offers a POSIX-only, opt-in persistent CPU renderer. It uses
ZMQRuntime's ordinary IPC endpoint lifecycle, a nominal `Renderer` ABC and typed
render tasks and commands. Diff preparation and large transcript fragmentation
run in CPU workers. Prepared Markdown parsing/highlighting additionally requires
the paired OpenHCSDev Textual hooks; stock Textual retains native Markdown parsing.

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
closes on unmount. Construction starts no service; fingerprinting and connection
I/O run off the UI loop when the first rendering task needs them.

This WIP PR still has a separately tracked compatible `agent-comms` pin/startup
gate. Tests below used development core dependencies and the paired Textual fork;
they do not establish clean installation/startup with the currently pinned core.
Installing the optional extra alone does not resolve that independent gate.

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
python tests/renderer_selection_pilot.py
python tests/persistent_render_pilot.py
python tests/persistent_renderer_ui_pilot.py
```

The real UI pilot creates two Toad instances using the supported constructor,
renders Markdown and a native tool diff, and checks reuse of the same service.
Existing process/transcript, Markdown lifecycle/row parity, diff lifecycle/style,
retained text and footer pilots are the compatibility checks for this checkpoint.

A manual desktop test was reported as “working pretty good.” A separate bounded
headless fixture (35 KB Markdown, 1,200 code lines) observed first completed updates
of 647–656 ms with new app-local workers, 454 ms with a reused persistent service,
and 1,409 ms starting that service cold. These are individual observations, not
terminal-pixel latency measurements. UI-loop pauses remained 45–57 ms. Cold startup,
Channels/tab loading and the separate <16 ms presentation target remain open.
