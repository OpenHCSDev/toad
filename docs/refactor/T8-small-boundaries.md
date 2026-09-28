# T8: Small boundaries

**Head audited:** Toad fork `main` at `43e57c9` (#108). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** upstream Toad. **Step 1.** Uses agent-comms' `TypedTable` and `FieldCodec` (TD1). Pattern IDs refer to the refactor-audit skill's catalog.

Three small boundaries, each with one clean form.

---

## 1. The terminal environment

**What is wrong (IMPL-12, MEMB-3).** The same six assignments appear byte for byte in two launchers:

```python
env["FORCE_COLOR"] = "1"          # shell.py:223-228 and widgets/command_pane.py:126-131
env["TTY_COMPATIBLE"] = "1"
env["TERM"] = "xterm-256color"
env["COLORTERM"] = "truecolor"
env["TOAD"] = "1"
env["CLICOLOR"] = "1"
```

A variable added to one launcher and not the other makes the shell and the command pane behave differently with nothing to show why. Separately, `command_pane.py:226` reads `os.environ["SHELL"]` at import time, so importing the module fails wherever `SHELL` is unset.

**Target.** One declaration, owned by the terminal: 

```python
@dataclass(frozen=True)
class TerminalEnvironment:
    """What every child Toad runs in a terminal sees. The variable names are external conventions."""
    variables: ClassVar[Mapping[str, str]] = MappingProxyType({
        "FORCE_COLOR": "1", "TTY_COMPATIBLE": "1", "TERM": "xterm-256color",
        "COLORTERM": "truecolor", "TOAD": "1", "CLICOLOR": "1",
    })

    @classmethod
    def for_child(cls, base: Mapping[str, str]) -> dict[str, str]:
        return {**base, **cls.variables}

    @staticmethod
    def login_shell(base: Mapping[str, str]) -> str: ...   # read at launch, once, with one declared default
```

Both launchers call it; the import-time read of `SHELL` moves into `login_shell`.

---

## 2. Session records

**What is wrong (MEMB-5, BOUND-1).**

- The session's shape is written twice, and **the two copies disagree**: the table's column is `prompt_count` (`db.py`, the `CREATE TABLE`), while the `Session` `TypedDict` declares `promot_count`. Nothing has noticed, because rows become sessions by `cast(Session, dict(row))` (`db.py:233`, `db.py:250`), an assertion nothing checks.
- The `meta_json` column holds untyped JSON with one key, `cwd`, which five sites spell: written at `acp/agent.py:1398` and `db.py:195` (a read-modify-write of the JSON), parsed with `json.loads` and read with `.get("cwd", None)` at `acp/agent.py:1441`, `app.py:2117` and `screens/session_resume_modal.py:117`.

**Target.**

```python
@dataclass(frozen=True)
class SessionMeta:
    cwd: Path

@dataclass(frozen=True)
class Session:
    id: int = field(metadata={"primary_key": True})
    agent: str
    agent_identity: str
    agent_session_id: str
    title: str
    protocol: str
    prompt_count: int
    created_at: datetime
    last_used: datetime
    meta: SessionMeta = field(metadata={"column": "meta_json"})   # a JSON column, decoded strictly

SESSIONS = TypedTable("sessions", Session)
```

- The table is declared by the row type through agent-comms' `TypedTable`, so the DDL, inserts and strict reads are derived and the two copies cannot disagree again. If `TypedTable` does not yet support a field stored as a JSON column, agent-comms' S12 agent adds it (extend, never fork).
- `SessionMeta` is decoded once, in the store; the three `json.loads` sites and the read-modify-write become typed reads and a typed update.
- `Session`'s `TypedDict`, both `cast`s and every `session["…"]` read are deleted.

**Persisted state.** The sessions database is the owner's session history, so it is durable. Every field name above matches today's column names exactly, so the existing database loads with no conversion; the misspelled name never existed in the database, only in the type.

---

## 3. Danger levels

**What is wrong (IMPL-2, BOUND-7).**

- `danger.detect` picks each level's highlight outside the enum: `if atom.level == DangerLevel.DANGEROUS and danger_style: … elif atom.level == DangerLevel.DESTRUCTIVE and destructive_style: …`.
- It also computes an overall level (`max` over the command's parts), which its **only caller discards**: `widgets/prompt.py:241` unpacks it into `_danger_level` and never uses it. The widget that would present a level, `widgets/danger_warning.py`, is one of TL0's dead modules.
- `analyze` walks bashlex's parse tree by comparing node-kind strings (`"list"`, `"operator"`, `"redirect"`, `"command"`) and probing `hasattr(node, "parts")`. The kind names are bashlex's API, an external contract; bashlex ships its own visitor (`bashlex.ast.nodevisitor`, with one method per kind) for exactly this.

**Target.**

```python
class DangerLevel(IntEnum):
    SAFE = 0
    UNKNOWN = 1
    DANGEROUS = 2
    DESTRUCTIVE = 3

    def highlight(self, styles: DangerStyles) -> Style | None:
        return styles.for_level(self)        # SAFE and UNKNOWN highlight nothing; each level decides once
```

- `detect` returns spans only, built from `atom.level.highlight(styles)`; the discarded aggregate goes. (If a warning feature is wanted later, it is built then, owning its own presentation.)
- `analyze` subclasses bashlex's `nodevisitor`, one method per node kind, replacing the string comparisons and the `hasattr` probe. The escalation rule (dangerous and outside the project becomes destructive) stays in one place, in the visitor.
- `SAFE_COMMANDS` and `UNSAFE_COMMANDS` stay: they are data about external commands, not a restated family.

---

## Guards

In `src/toad/`: the six terminal variables are assigned only in `TerminalEnvironment`; no `cast(Session`; no `json.loads` of session metadata outside the store; no `session["…"]` reads; no comparison against a `DangerLevel` member outside `DangerLevel`; no `hasattr` and no `.kind ==` in `danger.py`.

## Tests

- **Sessions:** one test that a sessions database written by today's code loads into `Session` records, and one round trip of `SessionMeta`.
- **Danger:** one table-driven test of command lines and the spans each highlights (`rm -rf ../x` destructive, `rm tmp/x` dangerous, `ls` nothing).
- **Terminal environment:** no test; one declaration used twice is enforced by the guard.
- **Delete** tests of the discarded aggregate level and of `DangerWarning`.

## New-case experiments

- **A terminal variable:** today two edits, in two launchers that can drift; after, one entry.
- **A session metadata field:** today a writer, a read-modify-write, and three `json.loads` readers each spelling the key; after, one field on `SessionMeta`.
- **A danger level:** today a new branch in `detect` and in any presenter; after, one member and its style.

## Done when

Both launchers use `TerminalEnvironment`; sessions are `TypedTable` rows with typed metadata and today's database loads; `detect` returns spans chosen by the level and `analyze` is a bashlex visitor; the guards pass.

## Dispatch

> **`toad-t8`:** Complete T8 per `docs/refactor/T8-small-boundaries.md`. Read `00-RULES.md` first. Three independent parts: one terminal environment declaration; sessions as a `TypedTable` with a typed `SessionMeta` (ask agent-comms' S12 agent for a JSON-column field if `TypedTable` lacks one); danger levels owning their highlight, with the discarded aggregate deleted and bashlex's own visitor replacing the kind strings. Keep the sessions database loading unchanged.
