# Local browser serving

Toad already supports `toad serve`, `toad run --serve`, and `toad acp --serve`.
These commands are **loopback-only**. External binds and non-local public URLs
are rejected. Open the private URL printed in the terminal, not the bare port;
the per-process token is exchanged for an HttpOnly, SameSite=Strict browser
cookie and immediately redirected to a URL without the token. The URL grants
access to your local Toad session; keep it private.

```shell
toad serve --host 127.0.0.1 --port 8000
toad run ~/project --serve --host 127.0.0.1 --port 8000
toad acp 'agent-comms-acp' --project-dir ~/project --serve --host 127.0.0.1 --port 8000
```

ACP accepts the project as positional `PATH` or `-d` / `--project-dir PATH`.
When both are supplied, the explicit option selects the project for terminal and browser sessions.

Open the printed URL in your browser. After authentication, the existing
WebSocket starts Toad; the unauthenticated server starts no Toad app or renderer
children. Closing the browser stops that Toad child. Comms owners keep their
normal independent lifecycle. Restarting the server creates a new private URL.

The Toad-only gate is attached before every `textual-serve` route handler,
including static assets, downloads, and the WebSocket that starts a Toad child.
It checks literal `Host`, matching WebSocket `Origin`, and a separate cookie
for each local port. Missing credentials, mismatched/null Origin, DNS-rebinding
Host, and external bind fail closed. The reviewed server API is pinned to
`textual-serve==1.1.3`. Serving is deliberately limited to localhost: do not
publish or forward the port to another machine.

## Verify the installed path

Install the candidate wheel, its pinned dependencies, and the developer
dependencies and the configured Comms native installation. The pilot uses
system Chromium (`/usr/bin/chromium`) and allocates
disposable roots under `~/wt`; it never writes the live Comms root or sends a
model prompt.

```shell
mkdir -p evidence/browser-serving
TOAD_BROWSER_EVIDENCE="$PWD/evidence/browser-serving" python tests/browser_serving_pilot.py
```

The pilot starts the actual CLI/server/child for all three commands. It checks
Host, Origin, bootstrap redirect, cookies, protected routes, rejection without
children, real Chromium rendering and keyboard input, and concurrent ports.
Screenshots and the acceptance receipt are retained in the evidence directory.
