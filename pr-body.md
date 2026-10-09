## Owner contract for #215

Declare `TurnOwner.captured_snapshot(widgets)` on the existing canonical turn family. Settled turns permit anonymous snapshot capture; active local or managed turns require original source/native-input claims. No stored permission or parallel lifecycle authority.

#215 owns the sole consumer migration, deletion of its old busy checkpoint gate, and the actual held-provider installed acceptance. This dependency preserves the merged #211 source checkpoint and does not repeat its completed native journey.

Source sanity: `git diff --check` passed. Actual installed consumer gate pending in #215. CI deferred by owner.
