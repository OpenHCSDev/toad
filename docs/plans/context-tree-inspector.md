# Read-only context tree and detail pane

## Status and intent

Planning-only draft, requested by the user. No implementation, installed-package change, runtime deployment, session export, or live acceptance is included. The initial clean local worktree is being removed; implementation ownership remains unassigned pending coordination with `agent-comms-ux`.

The user wants to explore what a displayed context budget (for example 61.2k tokens) contains, as an expandable tree rather than a long transcript. The target is the existing Textual frontend, not OpenHCS scientific code and not a separate full-screen terminal application embedded inside Pi.

## Proposed interface

Use Textual's `Tree` for navigation and a read-only, selectable text detail pane for the selected node. Show snapshot identity, capture time, coverage, and usage provenance above both panes.

Suggested organization:

- Active context
  - Compaction summary (optionally split by existing Markdown headings)
  - Retained and subsequent messages, with tool calls/results as children
  - Runtime configuration and active tool definitions, only when supplied by the runtime
- Archived history (not counted toward the active budget)
- Referenced material (not necessarily loaded; never silently read it)

Summary headings are a navigation projection, not independently verified semantic memories. Every detail remains linked to its original snapshot/message identity. Archived and active views must be visibly distinct.

Keyboard and pointer selection should update the detail pane; tree branches should expand/collapse. Search should identify matching nodes without expanding every large tool result. Refresh should preserve selection and expansion by stable IDs where possible. Do not preload or render all long detail bodies in the UI hot path.

## Data ownership and bridge

Keep context reconstruction at the Pi/native runtime owner. The Python widget must consume a structured, versioned snapshot rather than implement a second session-compaction algorithm.

A proposed local bridge carries:

- Schema version and snapshot ID, source session/leaf identity, capture timestamp.
- Coverage: reconstructed session context versus actual captured request; missing runtime fields must be explicitly unavailable.
- Active nodes with stable IDs, category, label, source identity and text/content blocks.
- Archived nodes separately, without adding them to active totals.
- Provider-reported usage with its observation identity/time, plus separately labeled per-node estimates and their estimation method.
- Optional tool definitions and runtime configuration, supplied only through an authorized source.

Reconstruct the selected active path with Pi's canonical context builder, honoring both legacy `firstKeptEntryId` and newer `retainedTail` compactions. Never count every historical branch entry merely because it exists in the JSONL file. Runtime/provider transformations and extension-injected changes may make reconstructed session context differ from the final request; the viewer must disclose that boundary.

Prefer explicit snapshot publication and refresh notifications after turns and compactions. The exporter must work without a native Pi TUI; the researched inspector's current `/context` command returns early when `ctx.hasUI` is false. A displayed snapshot is not proof of what a future or concurrent request sees.

## Token accounting

Separate provider-observed aggregate usage, estimated text-category contributions, output tokens, archived history, and configured reserve. Cached tokens are a subset of accounted input, not another independent context section. A displayed aggregate may refer to a previous response; label its age rather than presenting it as an exact current-request census.

Per-node counts are estimates unless produced by the actual applicable tokenizer and request serialization. Do not disguise proportional scaling as exact attribution. Calibration, when offered, must use only the active snapshot and a matching usage observation. Missing images/provider framing/runtime fields should be disclosed rather than fabricated.

## Research and reuse

- [Textual Tree](https://textual.textualize.io/widgets/tree/) is the intended widget primitive.
- [pi-context-inspector](https://github.com/yuriteixeira/pi-context-inspector) provides a useful TypeScript extraction/display reference; its documented interface is a tabbed overlay, not a tree.
- At inspection, `src/index.ts` reconstructs the Messages view via `buildSessionContext(...)`, but passes the entire `getBranch()` result into `buildTokenBreakdown(...)`. That implementation traverses historical messages and compactions before proportionally scaling to observed usage. Do not copy that accounting into an active-context budget viewer.
- [Trogon](https://github.com/Textualize/trogon) generates command-option forms for Click/Typer CLIs; it does not supply this application-state explorer and is not needed.
- [jless](https://jless.io) can explore an explicitly exported JSON snapshot as a prototype, but does not supply runtime provenance, accounting, or live Textual integration.
- [Context Viewer](https://github.com/auditt98/context-viewer) demonstrates a browser block tree for Claude Code/Cowork/Codex CLI; its documented parsers do not directly support Pi sessions.

Third-party references are design leads, not installed/tested dependencies. Prefer a small bridge and native Textual widgets; preserve licenses if implementation code is reused.

## Privacy and read-only boundaries

Never send inspected content into a model prompt or coordination message. No replay, compaction, branch mutation, history deletion, process startup, or automatic dereferencing of mentioned paths is permitted by browsing. Explicit export should be local, access-restricted, opt-in, and distinguish potentially sensitive content. Do not automatically expose provider-private reasoning or credentials. Render untrusted strings literally, not as executable terminal controls or markup. Do not commit live transcripts, actual context dumps, or secrets as fixtures.

## Implementation sequence (not started)

1. Agree the snapshot contract and runtime publication owner with `agent-comms-ux` and the Pi bridge owner.
2. Add a pure snapshot/view model and synthetic fixtures, with explicit active/archived/unavailable states.
3. Add the Tree + read-only detail widget and bounded/lazy detail preparation.
4. Add the smallest discoverable frontend entrypoint, coordinating shared screen write regions.
5. Implement headless runtime publication through the existing adapter boundary and refresh notifications.
6. Verify synthetic pilots, then perform an authorized installed-path check separately.

## Acceptance checklist

- Synthetic pilots: select/expand/collapse/search, literal hostile content, long detail bodies and narrow-terminal layout.
- Active path and compaction: alternate branches, legacy cut boundaries, materialized retained tails, repeated compactions, custom context messages, and non-context entries.
- Accounting: archived content excluded, no duplicate retained messages, estimate/observed labels, unmatched or stale usage, unavailable runtime configuration and image/framing uncertainty.
- Lifecycle: selection survives compatible refresh; superseded snapshots cannot overwrite newer content; closing releases owned work.
- Read-only: snapshot bytes and session state remain unchanged after browsing; no runtime calls or referenced-file reads are induced by selection.
- Installed acceptance: entrypoint opens the intended session, native exporter works headlessly, refresh follows the actual source identity, and ordinary frontend navigation stays responsive.

No checklist item is claimed passed by this planning-only PR. Do not merge a shell UI and represent it as a working live context inspector before the publication and provenance gates are qualified.
