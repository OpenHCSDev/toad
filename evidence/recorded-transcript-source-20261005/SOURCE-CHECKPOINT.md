# Recorded transcript consumer closure

Source-only branch `fix/recorded-transcript-source-20261005`, from actual Toad
main `ab5f5e0f02eadad7d0c2cf7d083344804be0e452`. Original Heis cleared these three
product seams; his #476 session presentation/viewport/retention work is separate.

Paired Core686 implementation `7244e985beaa1d99e4af23038937ff14c8a9eb32` owns the
declared live/recorded transcript identity and original provenance acquisition.
This draft's pyproject and lock revision bind that API. Only the literal Core
revision was changed; no dependency resolution, build, install or environment
was performed. No previous wheel/installed package is claimed source-equal.

## Product consumers

- `acp/transcript_reader.py`: original capture/bind and stale-publication
  reacquisition retain the recorded source. Supplying a conflicting source with
  a published identity refuses; a same-name live thread cannot substitute.
- `acp/comms_updates.py`: `OwnerSnapshotConsumer` asks the declared identity to
  publish a turn. Only the live member invokes the original callback, whose
  coordination/controller/root/incarnation checks and `TurnChangedUpdate`
  remain unchanged. Recorded provenance has no settlement/admission authority.
- `screens/historical_sessions.py`: the existing adjacent-page loader captures
  the selected recorded witness and performs the original fenced read. The
  selection generation, mounted history preparation, byte/receipt cursors and
  painted-handling path remain with their existing owners. Stale-source errors
  use the existing visible error path.

No new cache, page reader, codec, catalog, timer or focus workaround. No
annotation GUI/worker/performance accepted control is repeated. No peer checkout
was edited.

## Evidence and limits

Existing refactor-audit Package/Repository parsed all288 current Toad modules,
zero omissions. The three changed modules compile and parse under Python3.11
grammar; compiler was system Python3.14. The full paired source evidence is in
Core686 `docs/refactor/retained-routing-provenance-20261005/SOURCE-CHECKS.json`.
This is source evidence only: no application import, pytest/App/ACP/native/SDK,
provider/input, package/prefix/data or public access. Installed identity
roundtrip, stale-source reader and historical loader acceptance remain UNRUN.

Future qualification must name this paired source, normal artifacts and actual
eligible purpose. No holder/native authority or prior closed loan is inherited.
