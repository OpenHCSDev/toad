# Historical views companion

Core companion: https://github.com/OpenHCSDev/agent-comms/pull/144
Toad draft: https://github.com/OpenHCSDev/toad/pull/79
This Toad branch starts at main 32de161 (PR77/78 already merged). Dependency pins are
unchanged; parent owns candidate runtime installation and activation.

## Normal user path

- Open a normal Comms channel/DM. Scroll up into preserved history and down to the
  current live tail. Source-bound keys/cursors prevent overlapping source sequence
  numbers from hiding rows. Each historical row labels its preserved source identity.
- **Saved sessions** button / Ctrl+H opens the original identities and sessions,
  including timestamp collisions and older incarnations. This uses the existing
  bounded TranscriptHistory pager and SessionView layout/anchor owner.
- Click a historical sender (IRC or Markdown mode) to open that original identity,
  without selecting/launching its newer current counterpart.
- Historical reads are sparse painted-body receipts in the snapshot's existing
  ReadLedger. The live read document/schema and S4 partial ACK behavior are preserved.

## Verification

`tests/historical_views_pilot.py` passed mounted normal Comms: 85 historical and 3
live messages with colliding sequence numbers; user scrolling to oldest history;
original IDs retained; no live bus write; sparse historical ACK separated from live;
45 saved-session answers paginated; historical sender link selects original creation
10 while current identity remains 20. No provider or live owner was called.

`tests/channel_partial_paint_pilot.py` passed against both branches: partial ACKs contain
only painted bodies and later scrolling acknowledges remaining captured rows.

Commands (local runtime venv supplies installed Textual/Toad dependencies):

```sh
PYTHONPATH=/home/ts/wt/comms-historical-views-20260927/src:src \
  timeout 60 /home/ts/wt/comms-historical-views-20260927/.test-venv/bin/python \
  tests/historical_views_pilot.py
```

Five channel-reader cases also passed, including attachment/detachment refresh with
no new live sequence. The mounted DM rebind pilot passed: an old painted page cannot
acknowledge a hidden replacement identity.

The core `evidence/historical-views/HANDOFF.md` owns exact attachment, rollback,
source audit and remaining live acceptance. This implementation has NOT been deployed.
Saved-session inspection is read-only; it does not replay inputs, start an old owner,
or transfer source execution authority. The existing current restored session ACP
path remains available independently.
