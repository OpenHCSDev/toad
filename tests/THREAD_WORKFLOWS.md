# Local verification

Use the existing holder only after its original purpose, package preimage and
borrower clearance have been closed and a new package-only grant has been issued.
Keep the committed dependency pins as source identities. For a changed package,
build one normal file wheel directly from its already-owned published checkout
with the declared build backend; reuse a retained wheel when its complete assets
are equal. Install only the changed reviewed wheels into the granted prefix:

```sh
uv pip install --python "$REVIEWED_PREFIX/bin/python" --offline --no-deps \
  "$CHANGED_PACKAGE_WHEEL"
```

Pass each changed wheel explicitly for a paired stage. Preserve unchanged installed
dependencies. Local receiving does not run VCS dependency resolution or recreate
source clones merely to install already-owned source. This does not change the
separate hosted workflow, which has no local owned checkout or prepared holder.

Bind the actual archive origin and retained wheel hash through the existing
`ReviewedArtifact`, `PackageDirectUrl` and `InstalledSourceProof` owners, and compare
the complete installed assets to the declared Git source. Do not manufacture VCS
provenance for a file wheel. The original `RuntimeSelection.verify_stage` consumes
the candidate proof; the existing floor activation remains distinct and immutable.
Close derived build/source-cache claims after their consumers finish, retaining
standalone wheels, canonical Git and original proofs for the cleaner's shared
borrower/alias check. A wheel needed by rollback or a pending candidate is still
a keeper; a closed cache copy is not its source authority.

For a granted test holder that already has the declared test dependencies, run
`"$REVIEWED_PREFIX/bin/python" -m pytest`. The collector derives script pilots from `tests/`;
normal pytest tests and architecture guards are collected alongside them.
Use pytest selection (`-k`, a path, or `--collect-only`) rather than a manual roster.

Each pilot gets an isolated subprocess and private state/cache/temp roots. The
existing Comms child owners bound runtime and retire only processes carrying
that attempt's private identity, including workers that detached from the UI. A timeout is a failure, never a retry or skip.
`--pilot-timeout` adjusts the one-attempt budget. Logs remain in pytest's fixture
root for failures; use a persistent `--basetemp` under your worktree.

Test changes to Comms through the paired committed dependency pin and its
verified retained file wheel, not an editable shared checkout. The automatic
Debt ratchet is required; wider CI remains separately deferred.
Performance investigations live under `tools/performance/`, outside collection.

Native route pilots require `AC_NATIVE_COPIED_PACKAGE` pointing to the package
validated by the pinned Comms native builder. Read an existing matching immutable package
locally; the manual workflow invokes that owner on the exact Comms pin. A wrong
package fails verification before execution. No real provider credentials are
needed: the native model fixture binds only loopback. After a changed source
stage, compare the installed wheel assets before claiming installed-source
acceptance. Reusing an exact existing wheel needs no second build or unchanged
App, SDK, provider or physical recording.

The real pixel pilot also requires `st`, `Xvfb`, and `xdotool` on PATH; its Python dependencies are in the dev group. The saved settings pilot defaults to the representative saved document under `tests/fixtures`; set `TOAD_SETTINGS_SAMPLE` to test an explicit saved file without changing it.
