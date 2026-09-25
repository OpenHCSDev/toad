# Local browser serving (review candidate)

Toad already supports `toad serve`, `toad run --serve`, and `toad acp --serve`.
These commands are **loopback-only**. External binds and non-local public URLs
are rejected. Open the private URL printed in the terminal, not the bare port;
the per-process token is exchanged for an HttpOnly, SameSite=Strict browser
cookie and immediately redirected to a URL without the token. Do not share the
bootstrap URL or expose a live Comms root or credentials: browser use with live
sessions has not been approved.

The Toad-only gate is attached before every `textual-serve` route handler,
including static assets, downloads, and the WebSocket that starts a Toad child.
It checks literal `Host`, matching WebSocket `Origin`, and a separate cookie
for each local port. Missing credentials, mismatched/null Origin, DNS-rebinding
Host, and external bind fail closed. The reviewed server API is pinned to
`textual-serve==1.1.3`; Toad's Textual source pin is `06220c3837e8df0cb140b2d64205a0766398c9dc`.

Provider-free route regressions run with `python -m unittest discover -s tests
-p 'test_web_server.py'`. An opt-in Chromium paint/input check was performed
against a disposable XDG and `AGENT_COMMS_ROOT`, a fake ACP backend, and a
127.0.0.1 port; no real sessions, provider, or production service were used.
Do not treat that fixture result as clearance for live Comms use.
