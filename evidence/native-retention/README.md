# Installed ACP/native retention acceptance

See docs/audits/session_thread_panel_lifetimes_20260928.md for ownership,
matched measurements, failure interpretation and final-pin limits.

Reproduce from the own persistent worktree with a noneditable candidate wheel:

```sh
TMPDIR=$PWD/.artifacts/native-retention \
TOAD_ARTIFACT_ROOT=$PWD/.artifacts/native-retention \
AGENT_COMMS_ROOT=$PWD/.artifacts/native-retention/launch-root \
L0A_EVIDENCE=$PWD/evidence/native-retention \
NATIVE_RETENTION_RECEIPT=$PWD/evidence/native-retention/126-painted.json \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-689ce4b5d0592b9a/node_modules/@earendil-works/pi-coding-agent \
timeout 165 .venv/bin/python tests/native_session_retention_pilot.py
```

Fixture uses a loopback-only HTTP model endpoint and its own private data root;
real installed ACP, native Pi and UI execute. One owner/attachment remains fixed
across logical4/16/32/64 cohorts. No paid provider calls or64-agent claim.
Baseline6f and candidate share core2bfbdb23/Textuald9def32f/native689.
Native905 refusal remains strict; consume125 final bootstrap/pins before rerunning.
