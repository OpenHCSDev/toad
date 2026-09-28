# TL0: Legacy sweep

**Head audited:** Toad fork `main` at `511a1a2` (#106). **Rules:** [00-RULES.md](00-RULES.md), rules 1, 3 and 4. **Step 1**, alongside TR0, T1, T7 and T8.

At this head: 47 lines mentioning *legacy*, *compat*, *deprecated*, *backward*, *fallback* or *shim*, in 22 files (down from 53 in 28 at the index's head, so some were already deleted). Re-run at your head:

```
grep -rniE "legacy|compat|deprecat|backward|fallback|shim" src/toad/
```

---

## Targets

### Compatibility code and fallbacks: delete

| Where | What it is | Action |
|---|---|---|
| `acp/agent.py` (around 1471 and 1527) | "Publish model and thinking-level config options, with legacy fallback": reads an older `models` field when config options are absent | Delete if TD3 says the fork serves agent-comms agents only; otherwise it is an external ACP contract and moves to T2, typed |
| `acp/agent.py` (around 505) | handling for "legacy text-only rows" | Delete |
| `session_tracker.py` (around 94) | "Transport-only fallback for a view with no authoritative wire thread" | Delete under TD3's default: every view is a wire thread |
| `widgets/conversation.py` (around 466) | "Compatibility for callers selecting the original two routed kinds" | Delete; migrate the callers |
| `widgets/session_sidebar.py` (around 70) | "Compatibility for direct callers" | Delete; migrate the callers |
| `mcp_inventory.py`, `mcp_decision.py`, `screens/mcp_inventory.py` | capability negotiation (`_compatibility`, `POSITIVE_DECISIONS_CAPABILITY`) between Toad and your own pi MCP package | Pin the MCP package into the stack, installed with Toad, then delete the negotiation: two components installed together cannot be at different versions |

### A test hook in product code: delete

`widgets/comms_sidebar.py` reads `TOAD_COMMS_TEST_TARGET` from the environment to change its behaviour. Product code does not carry test switches; the test sets the target through the widget's real interface, or the hook's behaviour is deleted.

### Dead modules: delete on sight

Imported by nothing in `src/toad/`: `code_analyze.py` (27 lines), `gist.py` (33), `option_content.py` (51), `widgets/danger_warning.py` (65), `widgets/version.py` (5), `widgets/welcome.py` (31), `render_server.py` (30), and **`toad/os.py`**, an empty module that shadows the standard library's `os` and is imported only by tests.

Before deleting each, check it is not launched by name (`render_server.py` looks like a subprocess entry point, `python -m toad.render_server`, and stays if it is), then delete the rest with any tests that exist only for them.

### Stays: external names and innocent words

- **External APIs:** Rich's `legacy_windows` parameter; the `TTY_COMPATIBLE` environment variable; the persistent renderer's build-identity check in `render_zmq.py`, which refuses mismatched worker builds rather than adapting to them. Rename that check away from "compatibility" wording (to something like `require_same_build`), since it rejects rather than tolerates.
- **Innocent uses of the words,** such as choosing the previous tab in `app.py`, cursor direction, error messages about wrong result types, and the plain rendering shown while highlighting is pending: rename them so the guard can be absolute. Rename only in files no other surface currently owns; the rest are renamed by their owning surface (rule 1).

### Handed to other surfaces

53 `getattr(obj, name, default)` calls (27 in `Conversation`, 7 each in `app.py` and `acp/agent.py`) quietly tolerate objects of other shapes. They are removed by the surfaces that type those objects: T2 for the agent-comms boundary, T4 for `Conversation`.

---

## Decision

| ID | Question | Default |
|---|---|---|
| **TD3** | Does the fork serve ACP agents other than agent-comms' own? | **No.** The fork is agent-comms' client; upstream Toad remains the universal ACP client. Everything that exists only for other agents' older ACP shapes is deleted |

---

## Guards

Land when every surface has cleaned its own files:

- no identifier, comment or string in `src/toad/` matches the pattern above, except the named external APIs (Rich's `legacy_windows`, `TTY_COMPATIBLE`);
- no environment variable read in `src/toad/` whose name contains `TEST`;
- every module in `src/toad/` is imported somewhere or is a declared entry point.

---

## Done when

Every target above is gone or explicitly handed to its surface, the dead modules are deleted, the test hook is gone, and the guards pass. The PR reports lines deleted and added.

## Dispatch

> **`toad-tl0`:** Complete TL0 per `docs/refactor/TL0-legacy-sweep.md`. Read `00-RULES.md` first. Wait for TD3 before touching `acp/agent.py`'s legacy fallback and `session_tracker.py`. Delete, do not preserve; check each dead module is not launched by name before deleting it.

## TL0A closure receipt (2026-09-28)

PR118 integrates T1/119's published handoff and paired107/current Comms9e3dc3c.
All Part A target mechanisms and their current callers are removed. MCP now
uses Comms' verified pinned native package; arbitrary executable preferences
and capability negotiation are gone. Product test hook removed. Retained
filters use `visible_categories` directly. Dead modules deleted except actual
`python -m toad.render_server` worker entry point. The old queue/restored and
text-only branch was already deleted by107; current queueState remains.

Part B remains ordered after T2. Existing T4/T6 marker cleanup is recorded in
those surface files; T2 retains ownership of the full nominal ACP boundary.
Global marker/dead-module coverage lands after those owners close their files.
TL0A guards have no skip/exception mechanism. Runtime Rich/terminal names are
external contracts. Installed main-screen MCP decisions and Channels/settings/
filter tests are recorded in `evidence/tl0a/HANDOFF.md`.
