# Typed goal caller migration

Paired with core PR166 (3889a22), on top of coordination165. Current UI decodes flat goal protocol exactly once with Goal.from_wire; rendering and controls consume Goal.state declarations directly. Deleted old constructor and status/toggle/active accessor use throughout current Toad source and goal fixtures. Core test fixtures now send typed GoalAction commands; external UI Agent methods retain their current RPC signatures. Goal history/metadata fixtures serialize with the canonical to_wire boundary.

Seven existing actual owner/mounted pilots pass: set, pause/resume, retry, edit/CAS/history, standby/history, server polling and objective edit. First edit pilot failed because its synthetic metadata still serialized the old constructor fields; corrected fixture passes. Parent combined core89 tests pass. CI deferred. Authored caller migration; not a native equivalence proof.

Pins core3889a22 and latest merged Textual4fa6a9c. Parent owns paired wheel installation/live acceptance; source tests are not a deployment claim.
