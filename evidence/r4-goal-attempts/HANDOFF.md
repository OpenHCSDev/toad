# Paired R4 goal-attempt integration

Core PR190 is merged at 8300308e3333333ff057a642421f1f291253bc7a.
Toad now pins that revision and the goal-set pilot consumes Generation.lifecycle.ready.
No production Toad caller uses the removed Generation.state or exception aliases.

Source goal-set pilot passed fresh creation and replacement of a legacy blocked goal.
Installed core and Toad wheels in runtime-r4-goal-attempts-20260928 passed all three real owner routes:
- goal_set_owner_pilot: fresh/replaced goal and actual owner launch grant.
- goal_pause_owner_pilot: durable owner pause across reopen and explicit resume.
- goal_edit_owner_pilot: stable identity, revision CAS, history and execution projection.

Commands: env -u PYTHONPATH timeout 60 <candidate>/bin/python tests/<pilot>.py.
Raw outputs are the adjacent installed-*.log files. These use actual local RuntimeServer/ACP paths and isolated disposable data; they send no provider requests.
Core source handoff separately records 261 passing cases/one platform skip plus31 current restart/native/runtime seam cases.
Parent owns activation. CI deferred; no old input replay or live data edits were used for acceptance.
