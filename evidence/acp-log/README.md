# ACP log viewer acceptance

## Scope and ownership

Continuation of parent draft a24367b. Product changes are confined to
`acp/log_records.py`, `widgets/acp_log.py`, and `screens/file_preview.py`.
TR0/Toad117 ViewportPresentation ancestry is preserved. Current remote main
df0a758 is already an ancestor; no shared checkout or running install changed.

LogRecord is now a public ABC with response, method, failure, process diagnostic,
unparsed-record and fragment cases. The generic failure Boolean and formatting
branch are deleted. Protocol shape is decoded once; views consume record
behavior. LogSource and LogView catalogs come from the shared DeclaredFamily.
The current logger writes agent JSON and client Python dict repr; these are
distinct active sources, not readers for superseded formats.

Quota/provider interpretation and actions come exclusively from
agent_comms.acp_failure.ACPFailure.from_error(code, message, data), then its
title/description/action properties. No quota matching or nested-detail
extraction exists in this viewer.

## Installed acceptance

- `record-pages.txt`: real disk files, exact Raw reconstruction, an error across
  the nominal read boundary recovered by Earlier, grouped non-RPC stderr,
  explicit oversized-record fragments, and a sparse 850 MiB file read within
  the existing FilePreview.MAX_BYTES budget. The sparse input is removed.
- `installed-real-log-ui.txt`: passed using an owned bounded copy of the actual
  Agent_Comms_2026-09-28T17_04_01_806671.txt file (104260 bytes). Two new installed
  ToadApp mounts clicked the actual AgentResponse log link. Errors included the
  observed compaction refusal and provider usage-limit detail. Events, literal
  Raw, wrap toggle, End/rightward scrolling, selection, horizontal scrollbar,
  50x24 resize, Earlier/Latest, appended stderr, missing-file feedback/recovery,
  Ctrl+W with TextArea focus, and an ordinary Unicode file preview passed.
- `errors-real-log.svg`: actual app screenshot in its built-in textual-dark
  theme (ANSI terminal-default colors are not portable in SVG).
- `installed-boundary.json`: imported installed Toad and shared core modules;
  Textual fork16ede007. No source package override, mocked ACP backend, provider
  request or live write. The existing test fixture only tears down test-owned
  daemons and loads the installed app stylesheets.
- First incorrect test attribute and real narrow-grid resize failure receipts
  are retained. Responsive ItemGrid and fixed button rows resolved the real
  resize failure. Tests wait for Textual's real button active effect before a
  rapid same-button recovery click; production timers are not changed.

Run the disk pilot with the isolated installed interpreter. Run the UI pilot
with TOAD_LOG_UI_SOURCE pointing at the actual log and TOAD_LOG_EVIDENCE at this
directory; TMPDIR must be an owned disposable artifact directory, not a worktree.

## Dependency and limits

The tested public failure API is committed/published in core PR262 at
bb8a66089f3a5a72c4554ba1f29dc884cbf23896. Parent/T2 owns landing that API and the
paired dependency pin; the predecessor Toad manifest does not contain it.
Do not deploy this patch with the older core pin.

Raw displays the original page's UTF-8 text, with replacement only for invalid
UTF-8 bytes; it does not pretty-print or reconstruct JSON. A physical record
larger than FilePreview.MAX_BYTES remains explicitly fragmented and is not
claimed as a decoded failure. Earlier exposes the preceding slices; no read
loads the full oversized log. This is the existing preview bound, not a new
provider proof or summary limit.

Compared with a24367b, the three product files add223/delete58 lines. Growth
implements the new bounded diagnostic viewer and case owners; the superseded
generic record, formatted Raw and fixed control row are removed in place.
This receipt proves the focused installed paths listed above, not the entire
application or a complete NRA scan. CI is deferred.
