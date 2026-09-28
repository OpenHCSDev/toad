# R3 paired Toad input-document consumers

Parent integration branch; core R3 still finishing source acceptance. Production ACP delivery payloads are unchanged. Four direct core-facing pilots migrated to typed InputDispositions/InputDocument and AcpDeliveryCursors paths. Removed obsolete fixture calls to _read/_write/get/status and old CommsAgent forwarding attributes; notices are compared through typed immutable records while actual public UI dictionaries remain unchanged.

All four source pilots passed against R3 candidate: input_delivery_owner (932 historical notices, load/dismiss failures and stale updates), current_delivery_owner (actual owner queue, concurrently arriving input and notice-only dismissal), queue_view_backend (actual ACP admission/new/load/alias/restoration/surrogate-null/rebase plus mounted Prompt), native_input_attribution (saved/live routing and human quoted headers, display repair never ACKs). These checks send no paid-provider input. Raw logs are alongside this receipt. Core parent saved-input comparison preserves7780 rows/96cursors/2580UNKNOWN across original/live roots and typed copy roundtrip.

Core pin and installed acceptance remain pending final R3 source and merge. R1 stays live and usable. Parent owns native queue/compaction acceptance, paired pins and normal activation. CI deferred.
