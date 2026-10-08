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
