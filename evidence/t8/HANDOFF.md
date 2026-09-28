# T8 small boundaries — source checkpoint

Owner Pascal. Branch refactor/t8-small-boundaries-20260928, base fork main cc2d35c.
PR244 remains Darwin's package integration; no duplicate package edits here.

## Implemented

- TerminalEnvironment owns six child variables and launch-time shell selection;
  Shell and CommandPane use it. Explicit CommandPane env overrides retain precedence.
- Session is the existing core TypedTable owner, including declared SQL creation,
  insert/update and strict reads. SessionMeta owns cwd as Path and retained external
  agent_data snapshot. Existing column name meta_json is kept as one durable encoding,
  with typed values throughout; no alias/projection or old reader.
- Existing SqlStorage/JsonStorage extension points use SessionCodec (FieldCodec
  subclass) for Path/datetime text scalars; no copied JSON/row codec or schema roster.
- Session CRUD transactions run on worker threads; all current production and test
  session callers use attributes and typed metadata. Agent restore/project changes
  preserve the full external agent definition. Model-history behavior unchanged.
- DangerLevel implementations own highlighting/path escalation. bashlex visitor
  replaces node-kind recursion and hasattr. detect returns spans only. Dead
  DangerWarning, aggregate severity, enum switches, duplicate env assignments,
  raw session TypedDict/casts/handwritten DDL/JSON parsing are deleted.

## Evidence / concrete remaining seam

Six focused persistence/danger/deletion tests pass. Real SQLite writer contention
keeps the UI event loop progressing. Durable schema and fresh typed schema pass.
Read-only original database: 46 sessions, metadata keys exactly cwd/agent_data.

Mounted pilot initially could not import full terminal UI because newer core has
removed OBSERVATION_INTERVAL still imported by Toad main. Installed core instead
lacks Column.auto_increment. Existing PR107 owns this paired caller migration.
Preparing isolated combined PR107/T8 source acceptance; no replacement alias.
Failed logs retained. No provider sends, runtime changes or live writes.
