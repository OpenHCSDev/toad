# Retired private USER adapter pilot deletion

Base Toad main140436514d. Delete tests/default_route_private_user_pilot.py (285 lines). No product code, alias, or coordination schema added.

Behavior coverage inspected:
- Maintained tests/l0a_native_installed_pilot.py: real installed Toad -> ACP/worker/native Pi, private protocol bootstrap, mounted channel submission/participant triage/no-response notification, direct USER submission and actual native reply. Parent is running its final combined129+140/native64 acceptance; this cleanup does not claim a rerun.
- tests/default_route_pilot.py already checks editable pre-append rejection and uncertain USER send retains text, disables compose, and cannot submit twice. tests/default_route_cancel_pilot.py checks interrupted send and post-receipt paint cancellation. These older fault-injection pilots are not used as evidence of live-path readiness here.
- The deleted pilot's extra checks manually install a retired MutationStore schema, register participant state, query internal claim_batch_receipts tuples and inject failures into private append/os.open methods. Those are tests of superseded mechanisms; no internal shapes or fault-injection wrappers are ported.

Executed validation: Python3.14 parses every remaining src/tests Python file; repository-wide source/test search finds no MutationStore/register_participant/default_route_private_user_pilot references. No new tests or unchanged matrix. No paid calls/live writes; CI deferred.
