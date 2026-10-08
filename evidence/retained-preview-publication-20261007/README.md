# Retain source paint, not preparation placeholders

The running client retained 27 fragment bodies whose strips still contained
`Preparing preview`; their preparation widgets had already been removed.
One affected body was visible and no preparation task remained to finish it.
The read-only observation is retained in
`/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/live-preview-owner-snapshot.json`.

Two different contracts had been confused:

- Native live layout may use prepared rows before its after-refresh completion.
- Retirement must borrow the original committed resource and preserve its
  identity until the native children are removed.

The readiness queries also used native CSS class selectors for Python
capabilities. Textual's CSS inheritance follows the first DOM base;
`PreparedParagraph` inherits its worker capability through another base.
An empty CSS result therefore did not mean that all preparation was complete.

`PreparedPaintSource` declares the existing committed-resource capability.
`WorkerStatic` supplies its original getter without another state or cache.
`MeasuredViewportBody` now checks this nominal family before capture, after
native arrangement, after asynchronous byte measurement and under retirement
custody. This replaces the narrower ToolContent-only implementation. Live
Markdown and tool readiness also find their original workers nominally.
Markdown child publication borrows reader compensation, since it does not
mutate the native child tree.

The actual App check uses paged nested Markdown, native links and copy,
wheel direction reversal and stop, offscreen retirement and warm reentry.
It passed with source text retained and the same warm paint resource.
The source package and tests parsed without omissions; affected modules
compiled. Earlier reproduction and authored-consumer failures remain in scratch.

This corrects readiness membership and shared capture ownership (MEMB-2 and
IMPL-13). No production placeholder-string check, alternate renderer, readiness
registry or additional cache was introduced. Source App success does not prove
smooth frame times or acceptance of the user's already-open client.

The durable installed candidate passed the same paged Markdown check, existing
retained-paint and custom-converter controls, and saved-tool reconstruction.
That last control now asks the original body to materialize before accessing
its offscreen controls. All 16 tool declarations were acquired off the UI
thread; eight admitted bodies reconstructed the same declarations. Its
initial assumption that offscreen controls must remain mounted is preserved
in the failed run log. Installed results are in
`/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/committed-preview-installed.log`
and `committed-preview-installed-tools.log` beside it. No provider input ran.

## Frame coverage while replacement preparation runs

Frame coverage and retained-source evidence are different answers. The original
WorkerStatic already displays and measures preceding prepared rows while a new
request runs. PreparedPaintSource now supplies presentation_ready from those
resources, including the first display of a settled error. Markdown and tools
consume that capability; exact prepared_content publication and every retirement
identity check remain unchanged. No new state is stored.

The existing retained-source and paged native Markdown App checks passed together
(2 checks, 16.16 seconds), covering previous paint during source replacement,
links/copy, retirement and warm identity. Log:
/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/preceding-frame-coverage.log

The source sidebar App completed with zero provider inputs: left median 72.5 ms,
right 62.7 ms; worst observed frame 236 ms. This is headless frame admission, not
terminal-pixel or live smoothness acceptance. Prior runs had different widget
counts, so these observations do not establish a matched causal speedup.

The combined installed candidate passed both affected App checks (18.27 s),
including exact retained source and warm identity. It also includes native113.
The original installed sidebar App exited successfully with 518 widgets and no
provider inputs: left median 115.0 ms / p95 144.8 ms / worst 261.4 ms; right
77.6 / 92.4 / 134.8 ms. Latency remains unresolved. Installed logs:
/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/preceding-frame-installed.log
/home/ts/.cache/agent-scratch/preceding-frame-sidebar-installed-20261008/app.log
All 288 production and 417 test modules parsed without omissions; changed
production modules compiled. Full69 source/RECORD verification matched 954 assets
and 2857 RECORD entries.

## Assigned geometry owns preparation

The installed sidebar profile attributed 97 of 99 preparation acquisitions to
height measurement, taking about 19 ms cumulatively. Removing that side effect
alone passed measurement and resize controls but stalled initial paged history:
visible-only layout had not assigned widths to hidden rows required by complete
body retention. That incomplete deletion was restored and never published.
Its negative is preserved in pure-worker-measurement-source.log in the scratch
directory above (2 pass, 1 fail, 31.16 s).

The original DocumentViewport geometry demand now includes prepared descendants
of live bodies until capture. Native Resize assigns their geometry; height
measurement only borrows rows. MeasuredViewportBody supplies frame readiness
from the published visible source cohort, replacing the Markdown/tool copies.
Full-body capture still requires every exact committed paint resource. No new
state, cache, worker pool, queue or readiness waiver was added.

Native114 separately corrects StreamLayout: horizontal TCSS margins are now
subtracted from both assigned child width and measured wrapping width.

The combined installed build passed the original measurement/source,
resize/style/selection and paged native Markdown controls (3 pass, 18.44 s),
including native wheel reversal/stop, text/link/copy, full retirement and warm
paint identity. Log: assigned-worker-geometry-installed.log in scratch above.
Package AST parsed 288 Toad production, 417 test and 250 native modules without
omissions; changed production compiled. No provider inputs ran.
