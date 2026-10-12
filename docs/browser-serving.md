# Local browser serving

`toad serve` runs a Toad command line in a web browser. Everything after the
serve options is the ordinary Toad command line, started as its own process for
each browser tab, so the browser runs the same application as the terminal:

```shell
toad serve acp agent-comms-acp
toad serve --port 8001 acp agent-comms-acp --session NAME --project-dir ~/project
toad serve ~/project
```

`--port` (default 8000) and `--host` (default 127.0.0.1) come before the Toad
command line. Serving is **loopback-only**: `--host` accepts `127.0.0.1` or
`localhost` and any other address is refused. To use it from another machine,
forward the same port over SSH (`ssh -L 8000:127.0.0.1:8000 host`) and open the
printed URL there.

Open the private URL printed in the terminal, not the bare port. The
per-process token is exchanged for an HttpOnly, SameSite=Strict browser cookie
and immediately redirected to a URL without the token. The URL grants access to
your local Toad session; keep it private. Restarting the server creates a new
private URL.

Click the page once before typing: the page does not give the terminal keyboard
focus when it loads.

Each browser tab is a new `toad` process, exactly as a second terminal would
be: `toad serve acp agent-comms-acp` registers a new thread per tab, and
`--session NAME` reopens a saved one. Closing the tab ends that Toad process.
Comms owners keep their normal independent lifecycle.

The gate is attached before every `textual-serve` route handler, including
static assets, downloads, and the WebSocket that starts a Toad child. It checks
the literal `Host`, a matching WebSocket `Origin`, and a separate cookie for
each local port. Missing credentials, mismatched or null Origin, a DNS-rebinding
Host and an external bind fail closed. The server API is pinned to
`textual-serve==1.1.3`.
