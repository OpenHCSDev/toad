# Parked native preparation resource checkpoint

## Production relation

A tab park revokes publication and cancels its widget workers. It should retain
its existing prepared-page reader and data-only work while the mounted tree is
retained. The application PreparationRuntime remains the single owner of stored
results, with its existing64MiB/256entry limits and admission. There is no tab
cache, semantic history copy, new registry or status flag.

Previously TranscriptSourcePreparation.retire_source closed the reader scope on
both parking and final retirement; resume_source cleared the reader again. Thus
rendered native bodies and editor state survived A/B/A, but adjacent prepared
pages were discarded and the source read/render path was submitted again.

The existing source lifecycle now declares retirement of preparation:
ParkedSourceTranscript retains it; final states close it. Resume is declared on
the source state family rather than checked against a concrete type externally.
Repeated parking unwraps the same suspended source. Native publication still
requires source validation. Existing _reader replaces/closes the scope if loader
or through changes; actual Unmount closes it when the tree is disposed.

IDEN-3: resource lifetime belongs to the existing source lifecycle, without an
external state encoding. IMPL-12: retirement/resume share the family contract.
A new source lifecycle case inherits final release unless it declares retention;
no consumer dispatch table or alternative family is required. Twelve replaced
production lines are deleted across the two existing modules.

## Actual resource evidence

The existing ToadApp, private Comms registry and native journal reader, preparation
runtime/renderer, native TranscriptHistory and physical Pilot tab clicks execute.
No fake application, Agent, viewport or renderer is substituted. No ACP process,
provider, live original root or owner lifecycle mutation is used by this gate.

Installed b6 baseline: parking closes its scope and discards the prepared page;
two returns replace the reader/prepared result even though native bodies and
children/editor document/history/draft/reader survive. Preserved exit1 is the
assertion after normal application exit.

Checkout candidate: same reader and prepared result survive both returns, native
bodies/children and editor document/history/draft/reader survive, all remain within
budget. A warmed adjacent-page request performs zero native source reads on both
returns. An actual added native journal row advances the committed boundary:
old scope closes and its stored page is removed, a new reader prepares the new
boundary. Final retirement while parked closes that replacement scope and drops
its prepared page. Normal app exit, exit0.

The two positive receipts explicitly use PYTHONPATH=checkout/src with exact
installed Core2519/Text650 dependencies. The package direct_url for Toad in those
receipts describes the dependency environment's b6 base, not the source overlay.
source-provenance.json records the actual module location and changed source hashes.

Commands, each bounded45seconds:

```sh
PAGE_SCOPE_EVIDENCE="$PWD/.artifacts/warm-page-scope-baseline" timeout 45 \
  /home/ts/wt/toad-original-stream-message-headers-20260930/.artifacts/installed-accepted-retirement/bin/python \
  tests/retained_page_scope_pilot.py
PYTHONPATH="$PWD/src" PAGE_SCOPE_EVIDENCE="$PWD/.artifacts/warm-page-scope-invalidation-source" timeout 45 \
  /home/ts/wt/toad-original-stream-message-headers-20260930/.artifacts/installed-accepted-retirement/bin/python \
  tests/retained_page_scope_pilot.py
```

Use shell `timeout 45` (space) for the bound above. The baseline predates the added
source-advance phase; its unchanged A/B/A failure is preserved, not rerun.

## Remaining installed boundary

This is meaningful prepared-page resource reuse, not proof of retained terminal
Strip identity or faster first paint. Settled-return timers include fixed Pilot
waits and a page request; they are not selection-to-first-paint latency evidence.
Existing immutable original41MiB A/B/A +held PageDown/reverse/idle/End +physical
frames/profiling remains required for this source checkpoint before live readiness.
The full PR227 warm/rendered/velocity/growing-end/focus/T9 scope remains open.
Kepler alone owns the physical history-click helper; parent owns stage activation.
