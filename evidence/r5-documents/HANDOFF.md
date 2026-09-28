# Paired R5 document owners

Core195 merged at89314b0fe56de769cb956a63acd870e89e8dee43. Toad pins this revision; no production Toad direct store API changes were needed. The profiling fixture uses FieldCodec.encode instead of the removed Activity.to_wire.

Both source and installed paired wheels passed:
- profile_hot_paths_pilot:10000 activity records, incremental append/read and sidebar/tab updates; installed local median0.485ms for append/read.
- session_sort_pilot: all sorting criteria, stable selection and shared settings.

Each ran with60s process bounds. Installed runs unset PYTHONPATH and use runtime-r5-documents-20260928. Raw outputs adjacent. Source174 focused core cases include real owner restart preserving metadata/nonempty ledger, persistence failures and shared-reader/exclusive-writer checks. Parent real saved-document comparison retained current runtime/activity observations; no live/provider inputs were used. Parent owns activation; CI deferred.
