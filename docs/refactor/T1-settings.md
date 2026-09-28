# T1: Settings

**Head audited:** Toad fork `main` at `511a1a2` (#106). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** upstream Toad, extended by the fork. **Step 1.** Uses agent-comms' `DeclaredFamily` (TD1).

---

## What is wrong

**The setting's type is a string, and everything that depends on it is decided somewhere else.**

- **`Setting` is a tagged union written longhand** (`settings.py`): `type: str = 'object'`, with `choices` meaningful only for choice settings, `children` only for groups, and `validate: list[dict]` only for numbers. Illegal combinations are representable.
- **The schema is 51 settings written as nested dict literals** (`settings_schema.py`, 420 lines), each typed by a string (`boolean` 20, `object` 10, `choices` 8, `text` 5, `string` 4, `integer` 3, `number` 1). Validation rules are dicts typed by strings too (`{"type": "minimum", …}`).
- **A hand-written roster of the kinds:** `INPUT_TYPES = {'boolean', 'integer', 'number', 'string', 'choices', 'text'}`.
- **Each setting's type is stated twice:** once as a string in the schema, and again as a Python type at every read, `settings.get("tools.expand", str, expand=False)`. `Settings.get` coerces at read time through `isinstance` checks and `expect_type(value)` conversions. Whether to expand environment variables is a flag each caller chooses.
- **Settings are read by dotted string key: 45 reads of 31 keys across 13 modules.** `"diff.view"` is spelled five times in three modules, `"launcher.agents"` five times, `"sidebar.hide"` four. Each read restates part of the schema's structure, and a typo is a silent miss.
- **`screens/settings.py::schema_to_widget` is 140 lines** dispatching on the type string, and inside the integer and number branches dispatching again on validation-rule strings, written out twice; `compose` repeats the type dispatch.
- **`app.py::setting_updated` decides every setting's effect** in an 11-way `elif` on keys (`ui.column`, `ui.theme`, `ui.scrollbar`, `agent.thoughts`, …), each branch re-checking the value's type with `isinstance`.
- **The tool expansion policy is five strings** (`never`, `always`, `success`, `fail`, `both`) compared by hand in `widgets/tool_call.py::check_expand`.

---

## Target

### Setting kinds own their behaviour

A family of setting kinds, each owning its value type, its parsing (once, at load), its constraints as typed fields, and its widget:

```python
class SettingKind(ABC, Generic[T]):
    def parse(self, raw: object) -> T: ...          # strict, once, when the settings file loads
    def widget(self, key: str, value: T) -> Widget: ...

class Bounded:                                        # capability: minimum and maximum
    minimum: float | None = None
    maximum: float | None = None

class BooleanSetting(SettingKind[bool]): ...
class IntegerSetting(SettingKind[int], Bounded): ...
class NumberSetting(SettingKind[float], Bounded): ...
class StringSetting(SettingKind[str]): ...
class TextSetting(SettingKind[str]): ...              # multi-line
class PathSetting(SettingKind[Path]): ...             # owns environment-variable expansion
class ChoiceSetting(SettingKind[C]): ...              # choices are a family, not strings
```

`Bounded` is where multiple inheritance earns its place: integer and number settings share bounds and their validation, while the rest do not. The `minimum` and `maximum` dicts and their dispatch disappear.

### The settings are a declared, typed tree

```python
class UiSettings(SettingsGroup):
    column = BooleanSetting(title="Column layout", default=False, effect=App.apply_column)
    column_width = IntegerSetting(title="Column width", default=100, minimum=40, effect=App.apply_column_width)
    theme = ChoiceSetting(Theme, default=DefaultTheme, effect=App.apply_theme)

class ToolSettings(SettingsGroup):
    expand = ChoiceSetting(ExpansionPolicy, default=FailExpansion)

class ToadSettings(SettingsGroup):
    ui = UiSettings()
    tools = ToolSettings()
    diff = DiffSettings()
    # …
```

- **Reads are attribute access with typed values:** `app.settings.tools.expand`. No dotted strings, no type argument at the call site, no coercion at read time. A misspelled setting is an `AttributeError` a type checker catches.
- **Each setting declares its own effect;** when a setting changes, the app runs that setting's effect. `setting_updated` is deleted.
- **The settings screen is derived from the tree:** walk the groups, ask each setting's kind for its widget. `schema_to_widget` and the type dispatch in `compose` are deleted.
- **`settings_schema.py`'s dict literals, `SchemaDict`, `Setting`, `INPUT_TYPES`, `Settings.get` and `get_setting` are deleted.**

### Choices are families

`ExpansionPolicy` is a family on `DeclaredFamily` (affix `"Expansion"`, so `FailExpansion` stores as `"fail"`), each member owning `should_expand(status) -> bool`. `BothExpansion`, expanding on success or on failure, composes `SuccessExpansion` and `FailExpansion` by multiple inheritance, with its predicate combining theirs; nothing restates the two cases. `check_expand` calls the policy and stops comparing strings. Themes and every other choice setting follow the same pattern.

---

## Persisted settings

The settings file holds the owner's preferences, which are durable (rule 2). Derive each stored key from its attribute path so that it reproduces today's keys exactly (`ui.column-width` from `ui.column_width`, snake case to kebab case), and derive each choice's stored value from its family, reproducing today's strings. Then the existing file loads with no converter. Any key that cannot be derived that way is renamed once by a tool in `tools/cutover/`, which is then deleted.

---

## Guards

In `src/toad/`: no `settings.get(` or `settings[` with a string key; no comparison against a setting-type string; no dict literals describing settings; no `INPUT_TYPES`; no `setting_updated`; no string comparisons against expansion-policy values.

## Tests

- **One family test:** every setting kind parses a valid value, rejects an invalid one, and produces a widget.
- **One new-case test:** a test-only setting kind, and a test-only setting declared on a group, which appears on the settings screen, loads and saves, and runs its effect, with no other edit.
- **One load test:** today's real settings file loads into the typed tree unchanged.
- **Delete** the tests of `Settings.get`'s coercion, the schema dicts and `schema_to_widget`.

## New-case experiments

- **A new bounded integer setting with an effect.** *Today:* a dict entry with a list of validation dicts, a dotted-string read with a type argument at each use, and a branch in `setting_updated`. *After:* one attribute declaration.
- **A new kind of setting,** such as a colour picker. *Today:* a new type string, branches in both `compose` and `schema_to_widget`, `INPUT_TYPES`, and coercion in `Settings.get`. *After:* one `SettingKind` subclass.

## Done when

All 45 string-key reads are attribute reads, every setting declares its kind and effect, the deleted names above no longer exist, today's settings file loads, and the guards pass.

## Dispatch

> **`toad-t1`:** Complete T1 per `docs/refactor/T1-settings.md`. Read `00-RULES.md` first. Replace the schema, `Settings.get`, `schema_to_widget` and `setting_updated` completely; no dotted-string read survives. Keep today's settings file loading by deriving stored keys and values, never by a converter in `src/`.
