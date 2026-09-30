# Native resident cost, reconstruction reservation and readiness

**Production lines deleted: 0.** Kepler read-only source contribution to Heisenberg's main-based native-residency continuation after PR245. No competing patch, source test, app/capture, provider input or new runtime cache. References inspected on the tested source1de/receipt-only Ready d7c791; declaration/source bytes are pinned by the PR245 measurement receipt. Heisenberg owns the shared body capability and history/trim consumers.

## Distinct resource questions

`PresentationBudget.admit` at presentation_window.py:71 asks the body how many widgets must be reserved to materialize it. `MeasuredViewportBody.retained_widget_count` at viewport_body.py:96 returns the measured reconstruction cost while dormant. Retiring native children deliberately does not erase that reservation.

`TranscriptHistory.widget_count` at transcript_history.py:494 instead counts descendants still in the original native DOM. `_extend_and_trim` at :851/:877/:881 uses this live resident count for history admission/eviction. These values diverge after retirement. Replacing resident cost with the reconstruction reservation would over-count dormant bodies; overwriting the reservation with resident cost would under-budget future restoration.

No second semantic state authority is necessary. Derive resident resource cost from original native custody and its existing NodeList revision, while preserving the existing measured reconstruction reservation. Consumer reuse must choose the correct resource question through the original body capability rather than equating its two meanings. A resource measurement is not a new source, status, ready bit, epoch or body catalog.

## The dormant bit does not mean native removal is complete

| Existing owner | Original removal behavior |
|---|---|
| `TranscriptFragmentView.retire_body`, transcript_history.py:207 | Marks dormant through `retire_measurement`, then awaits removal of its children |
| `PreparedConversationMarkdown.retire_body`, prepared_markdown.py:73 | Marks dormant, then removes only immediate MarkdownBlock children |
| `StreamingMarkdown.retire_body`, streaming_markdown.py:62 | For paged content, marks dormant and removes its pager while retaining prefix resources |
| `Widget.remove_children`, Textual widget.py:4583 | Calls the original App prune transaction, not synchronous DOM removal |
| `App._prune`, app.py:4372 | Posts native Prune and starts AwaitRemove; native detach occurs later through unregister |
| `AwaitRemove`, textual/await_remove.py | Joins original teardown tasks and post-remove publication without transferring ownership to the waiting caller |

Therefore `body_dormant ? 1 : retained_widget_count` is incorrect during pending removal and for bodies retaining non-Markdown/prefix children. `DocumentViewport._reconcile` retires outside `HistoryWindow.history_lock`; `_restore_body` acquires that lock. A new resident-cost capability must remain correct before/during/after the actual native teardown transaction. The meaningful affected source check is a held real removal with its original native identities/revision, not a mocked counter or an unchanged broad UI capture.

## Readiness is another distinct relation

`TranscriptFragmentView.body_ready` at transcript_history.py:198 recursively checks nested ViewportBody readiness. `PreparedConversationMarkdown.body_ready` at prepared_markdown.py:37 also checks original Markdown loading. `TranscriptHistory._check_edges` at transcript_history.py:675 instead checks every native descendant's Mount completion, including non-ViewportBody widgets.

These contracts cannot be substituted unchanged. Native AwaitMount and the original window publication boundary are the extension owners. Accepted source state does not by itself certify descendants mounted by a later body recompose. Preserve pending-Mount, pending-remove and native frame publication obligations while eliminating repeated full-tree work; do not add a synced ready boolean or second watcher list.

## Same-recording global caller leads

The PR245 retained profile still reaches recursive readiness at nominal idle60.301 s and sidebar forced DOMQuery at return75.496 s. Its idle worker also reaches `message_notifications_for_references`→`presentation.window`→`notification_assignment.select`→TypedTable row decoding at47.924/48.199 s; at48.105 s it reaches `messages_for_references`→`source_references_unlocked`→publication attestation→FieldCodec. The frontend and backend owners received these exact caller leads directly.

The early idle samples can include settling and diagnostic observation. Chrome changed-stack groups do not allocate CPU shares or establish that a source read is redundant. Keep original kernel counters, source transactions, ProfileTrace and video marker limits. Do not turn this read-only review into another proof cache, codec, clock or monitor.
