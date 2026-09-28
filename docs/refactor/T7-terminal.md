# T7: Terminal emulator

**Head audited:** Toad fork `main` at `511a1a2` (#106). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** upstream Toad; the fork has not changed `ansi/`. **Step 1**, fully self-contained. Uses agent-comms' `DeclaredFamily` (TD1).

---

## What is wrong

This is the audit's clearest case of families that exist with their behaviour living outside them.

- **Commands.** `ansi/_ansi.py` already models the emulator's commands as types: `ANSIContent`, `ANSICursor`, `ANSINewLine`, `ANSIStyle`, `ANSIClear`, `ANSIScrollMargin`, `ANSIScroll`, `ANSIFeatures`, `ANSIMouseTracking`, `ANSIWorkingDirectory`, `ANSICharacterSet`, `ANSICursorPositionRequest`. They are `NamedTuple`s, which cannot share a real base class, so they are joined only by an `ANSICommand = (…)` union alias. **`TerminalState._handle_ansi_command` is a 223-line `match` over all twelve,** applying each command's effect from outside it.
- **Reads.** `ansi/_stream_parser.py` has a polymorphic family of reads (`Read`, `ReadUntil`, `ReadRegex`, `ReadPattern`, `ReadPatterns`). `ReadPattern` and `ReadPatterns` already own `feed`, `is_exhausted` and `unconsumed_text`; `Read`, `ReadUntil` and `ReadRegex` own nothing but `__init__`. **`StreamParser._feed` is an 85-line `isinstance` switch** handling those three from outside, and the other two besides.
- **Modes.** `ANSIStream._parse_csi` (160 lines) compares mode strings seven times (`1000`, `1002`, `1003`, `1004`, `1006`, `1007`, `1015`, the xterm mouse modes). `ANSIFeatures` is a bag of six optional booleans (`show_cursor`, `alternate_screen`, `bracketed_paste`, `cursor_blink`, `cursor_keys`, `replace_mode`) that `TerminalState` applies one by one. `FEPattern.check` dispatches seven ways on escape introducer characters.

The byte values and mode numbers are an **external standard** (ECMA-48 and xterm), so they stay exactly as they are. What moves is the behaviour attached to them.

---

## Target

### Commands own their effect

```python
class ANSICommand(ABC):
    def apply(self, state: TerminalState) -> None: ...

@dataclass(frozen=True, slots=True)
class ANSICursor(ANSICommand):
    delta_x: int | None = None
    # … the existing fields
    def apply(self, state): ...        # the body of today's ANSICursor arm

# ANSIContent, ANSIStyle, ANSIClear, ANSIScroll, … likewise
```

- Each `NamedTuple` becomes a frozen, slotted dataclass under `ANSICommand`, and **each arm of `_handle_ansi_command` moves into its command's `apply`.**
- `_handle_ansi_command` becomes `command.apply(self)`. The 223-line `match` and the `ANSICommand` union alias are deleted.
- `TerminalState` keeps its buffers, cursor and modes and the primitive operations commands call; everything command-specific leaves it.

### Every read owns its feeding

`Read`, `ReadUntil` and `ReadRegex` gain `feed`, `is_exhausted` and `unconsumed_text`, as `ReadPattern` and `ReadPatterns` already have, with the shared consumption loop on `StreamRead` as a template. **`_feed`'s `isinstance` switch is deleted;** the parser calls `self._reading.feed(…)`.

### Modes are declared once each

```python
class TerminalMode(DeclaredFamily, affix="Mode"):
    def apply(self, state: TerminalState, enabled: bool) -> None: ...

class MouseAnyEventMode(TerminalMode, declared_name="1003"): ...
class BracketedPasteMode(TerminalMode, declared_name="2004"): ...
class AlternateScreenMode(TerminalMode, declared_name="1049"): ...
# …
```

- Each mode declares its **external** number through `declared_name`, which is exactly the case A1's override exists for, and owns the change it makes to the terminal's state. The family's registry, with collision checking, replaces the string comparisons in `_parse_csi`.
- `ANSIFeatures`' six optional booleans are replaced by one `SetMode(mode, enabled)` command per mode change, applied by the mode itself. `ANSIMouseTracking` folds into the mouse modes.
- `FEPattern.check`'s seven-way dispatch on introducers becomes a family of escape sequence kinds keyed by introducer, the same way.

---

## Guards

In `ansi/`: no `match` or `isinstance` dispatch over command types, read types or mode numbers; no string comparison against a mode number outside the mode family; no `NamedTuple` commands.

## Tests

The terminal's behaviour is an external contract, so it is where contract tests belong:

- **One table-driven test:** a list of escape sequences with the screen state each must produce (cursor position, styles, modes, scroll region). One parametrized test covers every command and mode.
- **One new-case test:** a test-only command and a test-only mode work with no other edit.
- **Performance is a gate here:** the emulator sits on the hot path of every agent's output. `tests/large_stream_pilot.py` runs before and after, and the new dispatch must be no slower.
- **Delete** tests that assert on `_handle_ansi_command`'s or `_feed`'s internals.

## Done when

`_handle_ansi_command`'s `match`, `_feed`'s switch and the mode string comparisons are gone; every command, read and mode owns its behaviour; the contract test passes; the large-stream pilot is no slower; the guards pass.

## Dispatch

> **`toad-t7`:** Complete T7 per `docs/refactor/T7-terminal.md`. Read `00-RULES.md` first. Move each `match` arm into its command's `apply` and each read's handling into its own `feed`; declare each terminal mode once with its external number. Keep the byte values and mode numbers exactly as the standards define them. The large-stream pilot is your performance gate.
