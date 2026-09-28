# Toad refactor index

**Heads:** fork `OpenHCSDev/toad` `main` at `7a279b0` (#73); upstream `batrachianai/toad` at `dd4f90e` (2026-05-26), which is also the fork's base. **Rules:** [00-RULES.md](00-RULES.md).

Surface files are written one at a time, just before dispatch, against the head of the day. `main` moves too fast for plans written days ahead: in agent-comms' round 2, three of five surfaces were partly done before their files were written.

---

## Evidence

**Measured on both trees,** upstream at the base and the fork's head, all parsed with Python 3.14 (Toad requires 3.14; an earlier 3.12 pass silently skipped 9% of the fork and has been redone).

| | Upstream Toad | Fork head |
|---|---|---|
| Source | 109 files, 21,230 lines | 190 files, 43,891 lines |
| ABCs / enums / dataclasses / `TypedDict`s / Textual classes / plain classes | 4 / 2 / 65 / 19 / 106 / 133 | 21 / 8 / 184 / 20 / 196 / 237 |
| Functions dispatching on 3+ string literals | 16 | 31 |
| `isinstance` switches (3+ on one subject) | 10 | 14 |
| Raw record shapes (3+ string keys), of which bypassing an existing class | 29, 20 | 61, 27 |
| `getattr`/`hasattr` by name | 3 | 69 |
| Functions over 100 lines / classes over 500 lines | 9 / 5 | 16 / 9 |
| Legacy or compatibility markers | 10 | 53, in 28 files |
| **CI workflows** | none | **none** |

**On what the fork added,** per thousand lines of product code: string keys and string comparisons at upstream's own rate (0.9× and 1.0×); `None` checks, `isinstance` and `.get` about doubled; `type()` re-validation (absent upstream), long boolean chains (32×) and name-based attribute access (19.5×) introduced, in the style of agent-comms.

**NRA,** complete scan: 9 findings, 8 of them in fork code, mostly the rendering pipeline. Upstream Toad keeps its states in strings, booleans and `None` rather than enums, so NRA is structurally blind to most of it; the overlay above carries this audit.

**Upstream's god classes, which the fork doubled:**

| Class | Upstream | Fork head |
|---|---|---|
| `widgets/conversation.py::Conversation` | 1,686 | 3,042 |
| `app.py::ToadApp` | 632 | 1,889 |
| `acp/agent.py::Agent` | 773 | 1,886 |
| `ansi/_ansi.py::TerminalState` | 670 | 670 |
| `screens/main.py::MainScreen` | 224 | 502 |
| `widgets/tool_call.py::ToolCall` | 198 | 478 |

Agents extend whatever is already largest: the copy-the-context effect at the scale of classes.

---

## Surfaces

Organized by owned concept, whatever the origin; each surface covers upstream's and the fork's code alike.

| ID | Surface | Origin | Evidence | Target |
|---|---|---|---|---|
| **TR0** | CI, ratchet and guards, and a real test suite | both | The fork has no CI at all, and no automated tests: 228 `*_pilot.py` scripts are run by hand from a roster covering a tenth of them | A required check: the ratchet (agent-comms' R0, measuring `src/toad/`) plus every surface's guards, plus the test suite. |
| **TL0** | Legacy sweep | mostly fork | 47 legacy or compatibility lines in 22 files at `511a1a2`; a test hook read from the environment in product code; eight modules nothing imports | Same terms as agent-comms' L0: delete every converter, alias and legacy path; end every dual path with one path. |
| **T1** | Settings | upstream | *At `511a1a2`:* 45 reads of 31 settings by dotted string key across 13 modules; each setting's type stated twice (a schema string, and a Python type passed at every read); `schema_to_widget` is 140 lines.  `screens/settings.py` dispatches on `setting.type`'s seven string values **twice**, in `compose` and in `schema_to_widget`; `settings.py` reads its `SchemaDict` by string key in two functions; `app.py::setting_updated` is an 11-way string dispatch on setting keys with an `isinstance` switch on the value; `settings.get` switches on type twice; `tool_call_expand`'s values include `both`, which restates `success` together with `fail` | A setting-type family, each type owning its widget and its parsing; each setting declaring its own effect instead of a branch in `setting_updated`; the schema decoded once into records; the expansion policy as a family where `both` is derived. |
| **T2** | The ACP and agent-comms boundary | fork-heavy | agent-comms' extension (`_meta.agentComms`) is a bag of optional keys whose presence encodes what happened, spelled in six agent-comms modules and probed in Toad with `isinstance` and `.get`; wire keys hand-copied into Textual UI messages (the classes in `acp/messages.py` are UI messages, not decoders); capability flags between the two pinned components; 44 retired epoch names; name probes across the boundary; `Agent` 773 to 1,886 lines | The extension declared once, as records in agent-comms that producers construct and Toad decodes into the same classes; capability flags and hand decoders deleted; lockstep PRs |
| **T3** | Commands and actions | both | `Conversation.slash_command` is a 146-line, 11-way dispatch on command names; `ToadApp._run_thread_action` dispatches on `comms_*` action strings; `mcp_inventory.py` dispatches on button identifiers | A command family (agent-comms' `Command`), each command declaring its name, help and behaviour. Textual's own action strings go through one registry at the framework boundary. |
| **T5** | Comms interface | fork | `CommsSidebar` (1,043 lines) dispatches on five row kinds; `CommsChatView` (857); `TranscriptHistory` (680 lines, 15 long chains); repeated literal sets (`channel`/`irc`, `channels-sidebar`/`thread-sidebar`); source availability encoded as a boolean, as `None` and as a status string side by side | A row-kind family; a source-state family owning its presentation; one declaration per literal set. |
| **T6** | Rendering pipeline | fork | NRA (complete scan at `43e57c9`): `RenderCommandKind` paired with payload classes that already distinguish the cases; `RenderStatus` switched in the client; `RendererBackend`; `MessageCategory` grouped by hand; a `RENDER_TASK_TYPES` roster; `HistoryKind` duplicating the sidebar's row kinds under mismatched names | Families owning behaviour; `ConversationKind` built here and adopted by T5; `NavigationTarget` reassigned to T5 |
| **T7** | Terminal emulator | upstream | The families already exist with their behaviour outside them: a 223-line `match` over twelve command types in `_handle_ansi_command`; an 85-line `isinstance` switch over five read types in `_feed`, though two of the five already own `feed`; also `_parse_csi` (160 lines, a 7-way dispatch on modes); `check` (7-way on characters); `TerminalState` (670 lines); an `isinstance` switch in the stream parser | A handler registry keyed by control sequence, derived by class registration; terminal modes as a family. Self-contained, so it can run in parallel with anything. |
| **T8** | Small boundaries | upstream | Terminal environment set identically in two launchers; the `Session` `TypedDict` disagrees with its own table (`promot_count` against `prompt_count`) because rows are cast, never decoded, and session metadata is untyped JSON parsed at three sites; danger levels' highlight chosen outside the enum, with the computed overall level discarded by its only caller | One terminal environment; sessions as a `TypedTable` with typed metadata; danger levels owning their highlight |
| **T4** | Remaining god classes | both | `Conversation` 3,049 and `ToadApp` 1,902 lines, both still growing; turn ownership as strings; cursor actions checking `BlockProtocol` seven times; tab order and clipboard spread through `ToadApp` | Components that own state, after the other surfaces; a class-size ratchet in CI now |

---

## Order

| Step | In parallel | Why |
|---|---|---|
| **1** | **TR0**; **TL0** part A; **T7**; **T1**; **T8** | CI first, since nothing is checked today. The rest are disjoint and mostly upstream code. |
| **2** | **T2** (with its agent-comms lockstep); **T6** | The boundary is the central design task; the rendering pipeline is independent of it. |
| **3** | **T3**; **T5**; **TL0** part B | Commands and the comms interface both touch `Conversation` and `ToadApp`, after T2 has taken its part of them. |
| **4** | **T4** | Residual decomposition, against classes already shrunk. |

---

## Decisions

| ID | Question | Default |
|---|---|---|
| TD1 | Use agent-comms' shared abstractions directly (Toad already depends on agent-comms), or extract them into a small shared library? | Use them directly; extract only if a third consumer appears |
| TD2 | Make TR0's check required on the fork's `main` from the day it lands? | Yes |
| TD3 | Does the fork serve ACP agents other than agent-comms' own? | No: the fork is agent-comms' client, upstream Toad remains the universal one, and code that exists only for other agents' older ACP shapes is deleted |

---

## Surface files

Written one per prompt, just in time: [`TR0-ci.md`](TR0-ci.md), [`TL0-legacy-sweep.md`](TL0-legacy-sweep.md), [`T1-settings.md`](T1-settings.md), [`T7-terminal.md`](T7-terminal.md), [`T8-small-boundaries.md`](T8-small-boundaries.md), [`T2-agent-comms-boundary.md`](T2-agent-comms-boundary.md), [`T6-rendering.md`](T6-rendering.md), [`T3-commands.md`](T3-commands.md), [`T5-comms-interface.md`](T5-comms-interface.md), [`T4-god-classes.md`](T4-god-classes.md).
