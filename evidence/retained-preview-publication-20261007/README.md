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
