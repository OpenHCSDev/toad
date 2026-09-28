> Active implementation: Pascal, paired core/Toad TR0 branches. Newest owner override: CI remains deferred; workflows are manual and no merge gates are enabled. All acceptance is local against installed packages.

# TR0: CI, the ratchet, and a real test suite

**Heads:** Toad fork `main` at `511a1a2` (#106); agent-comms `main` at `3996e82` (#231). **Rules:** [00-RULES.md](00-RULES.md). **Step 1.** Everything else in this package depends on it.

---

## What is there today

- **No CI.** The fork has no `.github/workflows` at all. Every agent PR has merged unchecked.
- **No automated test suite.** `tests/` holds 228 `*_pilot.py` scripts, 226 of them run through a `__main__` block, none defining a `test_` function, plus 2 `test_*.py` files and 17 others. There is no pytest configuration.
- **A hand-maintained roster instead of a runner.** `tests/THREAD_WORKFLOWS.md` lists about two dozen commands to run by hand, a tenth of the pilots, and instructs installing an editable agent-comms from `/home/ts/.agent-comms` instead of the revision pinned in `pyproject.toml`. So what is tested by hand is not even the pinned stack.
- **agent-comms' ratchet exists but cannot be reused as it stands.** `tools/debt_ratchet.py` hard-codes `src/agent_comms/` and lives outside the installed package, so Toad cannot run it without copying it, and a copy is exactly what the rules forbid.

---

## Target

### 1. One ratchet, shipped in agent-comms (a lockstep agent-comms PR)

- Move the ratchet into the agent-comms package as a console script, `agent-comms-ratchet`, with a `--root` argument (`--root src/agent_comms` for agent-comms, `--root src/toad` for Toad).
- **Delete `tools/debt_ratchet.py`**; agent-comms' own workflow calls the console script. There is one ratchet, and Toad receives it through its pinned agent-comms dependency.
- This belongs to agent-comms' `refactor-r0`, which owns the ratchet.

### 2. One collector instead of 228 edits

- A single `tests/conftest.py` makes pytest collect every `*_pilot.py` as one test that imports the module and runs its entry point, with a timeout. A pilot passes when it completes without raising.
- **No pilot is edited to fit the runner.** The collector adapts to the scripts; rewriting 228 files into pytest style would be exactly the busy work rule 5 forbids.
- Scripts that are not tests, such as `profile_thread_open.py`, which takes `--messages` and writes profiles, move to `tools/performance/` with the other debugging scripts.

### 3. The workflow

`.github/workflows/ci.yml`, Linux, Python 3.14, `uv sync` against the pinned stack:

- **`ratchet`:** `agent-comms-ratchet --root src/toad` against the PR's base and head, then every guard test. Seconds long. **Required from the day it lands** (TD2).
- **`suite`:** every collected pilot, in parallel. Required as soon as it is green (see triage).

### 4. Triage: make the suite green without faking it

Run every pilot once in CI. For each failure:

- **It tests a feature that no longer exists:** delete the pilot. Tests of deleted code are deleted.
- **It found a real regression:** fix the code, never the assertion.
- **It is flaky or timing-dependent:** fix the timing dependency, or delete it if it protects nothing important. No retries-until-green, no skip markers.

Then make `suite` required.

### 5. Delete the manual procedure

- **Delete `THREAD_WORKFLOWS.md`'s command list;** the collector derives the suite from the directory.
- **Delete every hard-coded `/home/ts/` path** in `tests/`. Testing unreleased agent-comms changes means a lockstep PR that moves the pin, never an editable local checkout.

---

## Guards

- No `/home/` paths in `tests/` or `src/`.
- No `@pytest.mark.skip`, `xfail` or retry decorators outside a characterization test that names the bug it documents (rule 5's T3).
- The ratchet's root is `src/toad/`; `tools/performance/` stays outside it.

---

## Done when

- agent-comms ships `agent-comms-ratchet` with `--root`, and `tools/debt_ratchet.py` is gone.
- Toad's `ratchet` and `suite` checks both run on every PR and are both required on `main`.
- Every pilot either passes in CI or has been deleted, with the reason in the PR.
- `THREAD_WORKFLOWS.md`'s list and every `/home/ts/` path are gone.
- The PR reports pilots deleted, fixed and kept, and the suite's runtime.

---

## Dispatch

> **To `refactor-r0` in agent-comms:** Please ship the ratchet as the `agent-comms-ratchet` console script with a `--root` argument, delete `tools/debt_ratchet.py`, and point agent-comms' workflow at the script. Toad's TR0 depends on it.

> **`toad-tr0`:** Complete TR0 per `docs/refactor/TR0-ci.md`. Read `00-RULES.md` first. One collector, no edits to the pilots; triage every failure into delete, fix the code, or fix the timing, never skip or retry; delete the manual roster and every `/home/ts/` path. Done when both checks are required on `main`.
