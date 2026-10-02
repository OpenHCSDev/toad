# Busy coordination reads in transcript publication

Arendt owns the Toad publication consumer paired with Mendel's Core PR537.
Heisenberg retains viewport and workspace ownership in PR331.

The original330 crash rethrows an earlier SQLite error while joining a
transcript worker at shutdown. Core now distinguishes unavailable committed
reads from missing receipts, stale revisions and corrupt storage.

The existing TranscriptPublication family must retain mounted history and
its original source refresh when that typed unavailable outcome occurs.
Capture, source validation, page preparation and handling reads all use this
same publication boundary. No independent readiness state, empty receipt
substitute, broad worker exception suppression or SQL timeout change.

Source ownership and caller migration precede validation. The parent owns the
single affected installed busy-read journey and public publication. This draft
does not claim installed acceptance and makes no provider or public input.
