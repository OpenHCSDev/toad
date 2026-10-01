## Scope

Close the original `ToadApp.run_test` fixture cleanup after observed m01/u04 owner-wait failures. No product changes, timing changes, native/provider input, replay, metadata or default publication.

The original cleanup order is retained through Python's asynchronous exit stack and cleanup contexts. Remaining child and lock cleanup now run if the owner wait raises, and the primary run failure stays in the exception chain.

## Evidence and limits

- Original m01/u04 terminal failures and custody preserved by Core458 installed29.
- Source probe uses an actual owned OS child and the existing child cleanup, injects the observed owner-wait failure, and confirms child exit, final cleanup and primary exception chain.
- The Application context is controlled solely for this cleanup-source proof. No UI/native readiness claim or additional GUI journey.
- The initial direct callback counterexample and corrected proof are retained in `evidence/native-fixture-cleanup-20260930`.
- `tests/runtime_fixture.py`: 13 added / 6 deleted. Production deletions: **0**.

Kepler251 owns shared dialog/physical helpers; Heisenberg252 owns the actual Sidebar publication fix. Normal integration preserves those disjoint changes. Full continuous installed user acceptance still requires the corrected coherent pair.
