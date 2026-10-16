## P17: paint Core's delivered/read totals

Owner: toad-delivery-labels. Paired Core and Toad changes; P34/P36 real UI checks remain part of this batch.

The collapsed message label chose one agent's state and hid every count. Core MessageNotification now supplies ordering and one combined label, e.g. `Acknowledged · Delivered 1/36 · Read 0/36`. Toad paints that answer; its sorting and first-agent selection are deleted.

DeliveryProgress extends the existing AssignmentProgress family. PendingDelivery shares zero contributions for sent/unrecorded inputs; ReadDelivery shares proved delivery/read contributions for model reads and human reads, keeping those identities separate. External client acknowledgements contribute delivered only. Queued does NOT prove delivery: its existing active-owner pointer can describe unrelated work. No string-state switch, table, bool flag, new store, alternate codec or cache.

The old MessageNotification.read_at_ms field is deleted. The actual ShownToModelProgress owns that time and travels through the normal FieldCodec; constructor progress is required, not defaulted. Timed label formatting has one method. Core summary counts only typed proved progress; Toad has no recipient-count algorithm.

InputDeliveryBar has a different job: pending input jobs, including direct user inputs without a wire message. It cannot truthfully report a message audience. Its existing queue caption now also comes from Core InputDelivery.summary; the two kinds of count are not merged.

Before/after source evidence: `.artifacts/labels/{before,after}.txt` uses the existing refactor-audit parser over eight production/dependency roots:1037 modules, zero parse omissions. This is lexical source evidence, not a complete dynamic call graph. Actual imports/MRO/schema construction work. Real live message reads and normal codec round-trip give `Answered · Delivered 1/1 · Read 1/1` and `Acknowledged · Delivered 1/36 · Read 0/36`; no fake data or automated tests. One inspection command had a whitespace SyntaxError and was corrected; product imports then succeeded.

P36 source already declares all five status colour methods, including StatusPending and ThreadRetired, without a default. No replacement implementation added. P34 already uses Core's archive/stop declarations through the existing menu command path; view close remains distinct from stopping an agent. Actual saved-history archive/close and retired status screenshots are still required.

Not yet installed or visually checked. Codex owns the paired build/install; actual plain-st/isolated-display checks and labels.json follow. Preserve UNKNOWN9226 and all saved sessions; no replay.
