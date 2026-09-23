# Thread workflow verification

Run from the Toad worktree with the matching local agent-comms checkout installed:

```sh
uv pip install --python .venv/bin/python -e '/home/ts/.agent-comms[acp]'
.venv/bin/python tests/thread_controls_pilot.py
.venv/bin/python tests/model_picker_pilot.py
.venv/bin/python tests/provider_login_pilot.py
.venv/bin/python tests/prompt_queue_pilot.py
.venv/bin/python tests/project_path_pilot.py
.venv/bin/python tests/session_sort_pilot.py
.venv/bin/python tests/channel_views_pilot.py
.venv/bin/python tests/sidebar_navigation_pilot.py
.venv/bin/python tests/goal_details_pilot.py
.venv/bin/python tests/path_filter_pilot.py
.venv/bin/python tests/channel_unread_follow_pilot.py
.venv/bin/python tests/sidebar_latency_pilot.py
.venv/bin/python tests/irc_wrap_pilot.py
.venv/bin/python tests/comms_pilot.py
.venv/bin/python tests/e2e_pty.py
.venv/bin/python tests/large_stream_pilot.py
.venv/bin/python tests/committed_history_pilot.py
.venv/bin/python tests/transcript_history_pilot.py
.venv/bin/python tests/long_message_pilot.py
.venv/bin/python tests/reply_route_pilot.py
.venv/bin/python tests/resize_render_pilot.py
.venv/bin/python tests/resize_pty.py
.venv/bin/python tests/profile_thread_open.py --messages 10000
.venv/bin/python tests/profile_thread_open.py --profile /tmp/opencode/thread-open.prof
```

`thread_controls_pilot.py` uses a real ACP subprocess with a deterministic Pi
protocol fixture. It verifies model changes, ordinary replies staying out of the
wire, model-specific thinking-level selection and persistence, durable goal
pause/resume/completion/clear, private and channel IRC messages,
sender/destination navigation, and reusing existing thread tabs.

`e2e_pty.py` drives a separate terminal PTY; it does not send desktop input.
Its close-view check verifies that the detached executor remains alive. Test
fixtures explicitly stop their own daemons during cleanup; application shutdown
is deliberately insufficient for that cleanup.

`sidebar_navigation_pilot.py` captures every non-batched painted channel-panel
frame across view transitions, including nested thread selection. It catches
temporary empty/collapsed trees that final-state assertions miss.
`channel_views_pilot.py` covers persisted channel-list/member sorting, notices,
the participant roster, and Ctrl+W/Ctrl+J composer editing.

`provider_login_pilot.py` exercises ACP terminal-auth discovery, the existing
ActionModal/CommandPane, keyboard input, automatic success dismissal, model refresh,
preserved transcript/draft,
and subprocess cleanup on both cancellation and app shutdown. Its provider uses
an isolated credential fixture; it does not authenticate a real account.

`prompt_queue_pilot.py` exercises concise model-provided titles, deferred user
blocks, Enter-to-queue, Ctrl+Enter-to-steer, consumption order, and restoration of
unprocessed input on cancellation through real ACP and fixture Pi RPC subprocesses.

Live Pi 0.85.1 verification additionally covered a model-generated topic title,
completion of the original answer before processing a queued follow-up, and the
official account/provider picker inside Toad's embedded terminal. A native Pi
steering check changed the active answer before the queued follow-up ran.
The login UI was cancelled before account authorization; actual subscription sign-in
still requires completing Pi's browser flow.

## Fork-opening profile

Measured on this Linux workstation, 120×40 terminal, using repeated Markdown list
messages and the actual ACP load-session path:

The backend and model catalog are deterministic fixtures to isolate replay and
rendering costs; these timings do not measure model-provider startup or inference.

| Transcript | Before opening | After opening | Before revisit | After revisit |
| --- | ---: | ---: | ---: | ---: |
| 100 messages | 74.46 s | 1.22 s | 7.79 s | 0.48 s |
| 10,000 messages / 14.7 MB | timed out at 120 s | 1.18 s | — | 0.30 s |

These are unprofiled wall-clock measurements, not CI timing assertions.
The 100-message baseline mounted 4,891 widgets and stalled the event loop for up
to 7.37 s. After the change, the same workload mounted 97 widgets; the maximum
observed event-loop gap was 0.18 s. With allocation tracing enabled, the 10,000
message run peaked at 18.7 MB of Python allocations in the Toad process (this
excludes the ACP subprocess and includes UI setup during attachment).

cProfile showed repeated Textual layout/reflow dominating the old path: 82 s of
the timed-out profiled run were spent in `_refresh_layout`. Saved history had
been fed into live Markdown streams, repeatedly creating and laying out widgets.

The replacement reads backward with bounded buffers, sends a negotiated ACP
history page, and mounts a small recent window. Earlier/later pages load
automatically while scrolling; End or **Jump to latest** returns to the tail.
Long saved and live messages render in small fragments rather than mounting the
entire Markdown tree. The complete on-disk transcript is retained. Committed
turns replace accumulated live blocks with the same bounded history projection
when the view is following the tail; session metadata must be ready first.

`large_stream_pilot.py` checks that a growing table-heavy answer has bounded
widget count and its final line remains reachable across terminal widths.
`reply_route_pilot.py` verifies that channel destinations survive live rendering
and history replay without leaking onto subsequent private replies.
