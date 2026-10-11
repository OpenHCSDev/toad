# Theming, pywal, true colour and effects

Status, 2026-10-10: design done; the first increment is implemented (see
[First increment](#first-increment-implemented)). Owner: the theming workflow.

Toad's target layering (Tristan, 2026-10-09):

1. Core (`agent_comms`) holds comms meaning.
2. A frontend-neutral UI layer holds view models, roles, line blocks and per-frame
   presentation. It has no Textual or Qt imports.
3. Backends render layer 2. Today that is Textual; PyQt comes later.

Theme meaning belongs in layer 2: the palette, semantic colours, the colour each
role is drawn in, effect choices and colour depth. The Textual backend only
renders that meaning, as CSS variables, Rich styles, terminal colour output and
effects.

What Tristan asked for (this session, 2026-10-10): "refactoring the theming and
integrating textual effects and true color term support for pywal … behind the
backend abstraction layer", then "adding textual effects and animations while
keeping a high framerate would be cool". He has said nothing else about it: the
plans, docs, Git history and bus have no other mention of pywal or text effects.
He already runs Toad with pywal through ANSI themes (commit `65e8a6038`,
2026-09-23, tuned `:ansi` hover contrast under a pywal palette).

## 1. Census: who decides colour today

Method: Python `ast` over `src/toad` (273 modules; 7 `.tcss` files; 100 CSS
documents including `DEFAULT_CSS`), reading each site, and reading the Textual
fork (`textual-main`, 629 commits on Textual 8.2.8) and Rich 15.0. Line
numbers below refer to `main` at `27f455803`.

### Facts, owners and consumers

| Fact | Owner before | Consumers | Problem |
|---|---|---|---|
| Role → colour for transcript lines | `widgets/transcript_lines.py` `LineTheme.from_app`, a table of 8 entries read from `app.current_theme` | `RichLineRenderer` (4 sites), `transcript_history.py` (5), `line_markdown.py` (4), `transcript_fragments.py` (2) | A backend table holds meaning. Two widgets each cache their own copy, and `transcript_history.py:446` builds a third. The user and agent colours are the reverse of the live widgets' CSS (`UserInput` bar `$secondary`, `user_input.py:21,35`), so a sent prompt changes colour when it is committed. |
| Muted text | `transcript_lines.py:49-51` blends the foreground 60% over the background | `MutedRole`, `ThinkingRole`, dividers | Under ANSI themes (the default, `ansi-dark`) both colours are `ansi_default`, the blend returns the default colour, and muted and thinking text are **not muted at all**. Textual's own `$text-muted` is `auto 60%` (a contrast colour) in true-colour themes and `ansi_default 50%` in ANSI themes. |
| Palette ANSI colours map to under a true-colour theme | `app.py:67-91` `DRACULA_TERMINAL_THEME`, assigned in `on_load` (`app.py:383`) | Textual's `ANSIToTruecolor` filter, `Content` conversion, `_styles_cache` | Fixed table. The light palette is never set (Textual's Alabaster). A pywal palette cannot reach it. |
| Theme catalog | Textual `BUILTIN_THEMES` (20 themes) | `ThemeChoice` setting (`preferences.py:60`, default `ansi-dark`) → `app.theme`; settings editor | Toad registers nothing of its own. A future PyQt frontend could not offer the same themes. |
| Is the theme ANSI? | Three deciders: `app.current_theme.ansi` (`tool_output.py:447`, `tool_content.py:155`, `patch_diff.py:454,488`); `app.theme.startswith("ansi-")` (`tool_call.py:352,362`, `screens/store.py:150,396`); CSS `:ansi` (43 selectors), which Textual answers with `app.native_ansi_color` | patch preparation, pills, 43 CSS rules | Three answers. Only `:ansi` honours an `App.ansi_color` override. |
| Patch theme key `(ansi, dark)` | Built in 4 places (`tool_output.py:447`, `tool_content.py:154-156`, `patch_diff.py:454-455,488-489`) | `PatchRenderTask`, `PreparedPatch.theme` | No owner. |
| Syntax theme | `rich_preparation.py:160,254-255` (`"monokai"`, `"auto"` → `ansi_dark`/`ansi_light`), `worker_static.py:77`, `patch_diff.py:183` (`ansi_dark` regardless of dark), `textual_diff_view` | tool output, file previews (`file_kind.py:18`, always monokai), diffs | Three independent choices. |
| Colour depth of the host terminal | Rich's `Console._detect_color_system`, through Textual's `constants.COLOR_SYSTEM` (`TEXTUAL_COLOR_SYSTEM`, default `auto`) | `Strip.render` (downgrade on output); `worker_static.py:175` passes `app.console.color_system` to workers | Detection reads `COLORTERM` then `TERM`'s suffix only; no terminfo. Tristan's `st` (`TERM=st-256color`, no `COLORTERM`) is therefore driven at **256 colours** although `st` shows 24-bit colour. Checked: the live `toad` process has `TERM=st-256color` and no `COLORTERM`; Rich detects `256`. |
| Colour depth of worker consoles | `transcript_lines.py:119` hard-codes `"truecolor"` | Markdown rendering in workers | Inert (segments keep full colour; the app downgrades on output) but a second answer. |
| Colour environment for child programs | `terminal_environment.py` (`TERM=xterm-256color`, `COLORTERM=truecolor`, `FORCE_COLOR`, `CLICOLOR`) | `Command.for_script` only | This is what Toad's embedded terminal emulator accepts (it parses 24-bit SGR), a different fact from the host depth; but ACP terminals, the MCP decision PTY and the agent process do not get it. |
| Selection style | Textual `screen--selection` | `worker_static.py:170,317` and `patch_diff.py:318` through `Style.from_styles`; `terminal.py:345` through `get_visual_style` | Two methods. |
| Theme-change invalidation | none | `watch(app, "theme")` ×3, `notify_style_update` overrides ×7 | Watchers of `"theme"` run before Textual rebuilds the CSS variables, so they must recompute lazily; they do not run when a theme's colours change under the same name. |
| Hard-coded colours | — | 117 CSS values: `#ad8bf5` ×2 (`session_sidebar.py:29,39`), `white`/`blue` ×3, `black N%` scrims ×13, ~30 `ansi_*` in `:ansi` rules, ~45 `transparent`, ~15 `ansi_default`; 12 hex in `mandelbrot.py`; 6 `ansi_*` in `throbber.py:21-26` | The `:ansi` twins are how ANSI themes get readable colours; the hex and named colours ignore the theme. |

CSS variable use (CSS only): `$primary` 43, `$text-muted` 43, `$background` 26,
`$text-secondary` 17, `$text` 16, `$text-primary` 14, `$foreground` 14,
`$accent` 13, `$secondary` 13, `$warning` 12, `$surface` 11, `$panel` 11,
`$error` 8, `$text-success` 8, then 20 more below 6 each. Python `Content`
markup uses 91 more (`$text-success` 12, `$text-secondary` 11, ...), 32 of them
in `highlighted_textarea.py`. All are Textual's generated variables
(`design.py`), so they follow any registered Textual theme.

### How workers receive theme state

Render workers hold no theme state; it travels inside each task:
`TranscriptLinesRenderTask` carries a pickled `LineTheme` (resolved Rich
styles), `RichRenderTask` a `RichPresentation` (styles, `color_system`, `dark`),
`PatchRenderTask` two booleans, `SyntaxSource` a theme name. Task identity is
the SHA-256 of the pickled task (`work_preparation.py:154`). A pickled Rich
`Style` includes its per-process salted `_hash` once something has hashed it,
so the same theme can produce two task keys (cache churn, not wrong output).

### Per-frame colour work

Transcript lines, the live tail and Rich previews keep finished strips; a
frame does no colour work for them, and `Strip.render` keeps each strip's
terminal sequence. Colour downgrade (true colour → 256/16) happens once per
style through `lru_cache`s (`strip.py:749`, Rich `Color.downgrade`). A theme
change costs one CSS re-parse and restyle of every node
(`App.refresh_css`) plus fresh strips: a one-off, not per frame. The real
per-frame colour work today is `PatchDiffCode` (re-parses span styles on every
paint, `patch_diff.py:292`), `future_text.py:75-81` (blends per animation
frame) and `ThrobberVisual` (one cached row, sliced per frame).

## 2. pywal

Installed: `python-pywal 3.3.0` (`/usr/local/bin/wal`); i3 runs `wal -R -q` at
login (`~/.config/i3/config:2`).

- **The file.** `wal` writes `colors.json` in `$PYWAL_CACHE_DIR`, else
  `~/.cache/wal` (`pywal/settings.py:21`): `wallpaper` (path), `alpha`
  (string), `special` {`background`, `foreground`, `cursor`}, `colors`
  {`color0` … `color15`}, each `#rrggbb` (upper or lower case).
- **When it changes.** On `wal -i <image>`, `wal --theme`, `wal -R`. It is
  written in place, not atomically (`util.save_file`: `open(path, "w")` then
  write), so a reader can see a truncated file until the writer closes it.
- **Sequences.** `wal` also writes OSC 4 (palette 0–15), OSC 10/11/12
  (foreground, background, cursor) to every `/dev/pts/*`. Every open terminal
  recolours its ANSI palette at once; running programs are not told.

What that means for Toad:

- **ANSI themes** (`ansi-dark`, the default) already follow pywal live, with no
  repaint: they emit palette indexes, and the terminal changed the palette.
  But they cannot blend, shade or fade (Textual does not know the RGB values),
  which is why muted text was not muted.
- **A true-colour pywal theme** must read `colors.json`, build the theme and
  the matching ANSI palette, and apply both again when the file changes.

Consumption: decode `colors.json` **once**, at the boundary, with the existing
`FieldCodec` into the neutral `TerminalPalette` (pywal's format is honoured
exactly: unknown keys are rejected, so a `pywal16` file with `checksum` fails
loudly instead of being half-read). React to the writer's close
(`IN_CLOSE_WRITE` through watchdog, which Toad already ships), when the file is
whole. A failed decode is reported as an error notification and the previous
colours stay; nothing is substituted.

## 3. True colour

How depth is decided today: Textual builds its Console with
`color_system=constants.COLOR_SYSTEM` (`app.py:631`); `auto` makes Rich check
`COLORTERM` (`truecolor`/`24bit`) and otherwise the part of `TERM` after the
last `-` (`256color` → 256, `16color` → 16, else 16). No terminfo, no terminal
query. The driver plays no part. Painted strips keep their terminal sequence
(`Strip._render_cache`, not keyed by depth), so depth cannot change while the
app runs.

What is wrong:

1. `st` advertises truecolor nowhere Rich looks (`st-256color` terminfo has
   no `Tc`/`RGB` flag and `st` does not set `COLORTERM`), so Tristan gets 256
   colours: every true-colour theme is snapped to the 6×6×6 cube.
2. kitty's terminfo has `RGB`, but Rich reads `xterm-kitty` → 256.
3. A second answer in `transcript_lines.py:119`.

One owner: `toad.colour_scheme.ColourDepth` (neutral), decided once at launch
from the environment: `COLORTERM`, then terminfo (`Tc` or `RGB` flag → 24-bit,
`colors` ≥ 256 → 256), then `TERM`'s suffix, else 16. The Textual backend
hands it to the App through a new `App.get_color_system()` hook in the fork
(the same shape as `get_driver_class`), so the Console never runs Rich's
detection for Toad. What Toad's embedded terminal accepts (`TerminalEnvironment`)
stays separate: it describes Toad's own emulator, not the host.

For `st` the right fix is outside Toad: `st` should say it supports 24-bit
colour. See decision D1.

## 4. Effects and animation

### What "textual effects" can mean

- **TerminalTextEffects** (`terminaltexteffects` 0.15.0, MIT, pure Python, no
  dependencies; 36 effects: Decrypt, Beams, Print, Matrix, Highlight, Sweep,
  Wipe, Slide, Expand, ...). `for frame in effect` yields frames as SGR strings
  without touching the terminal. Two traps: by default it sleeps to hold its
  frame rate (`frame_rate=0` turns that off), and building an effect does all
  path and gradient work up front.
  Measured on a 40×10 text, `frame_rate=0`, host load ~3.4:

  | Effect | Build | Per frame | Frames | Length at 60 fps |
  |---|---|---|---|---|
  | Print | — | 0.19 ms | 450 | 7.5 s |
  | Sweep | 25–166 ms | 0.31 ms | 220 | 3.7 s |
  | Decrypt | 185–237 ms | 0.45 ms | 893 | 14.9 s |
  | Wipe | — | 0.46 ms | 138 | 2.3 s |
  | Slide | — | 0.8 ms | 129 | 2.1 s |
  | Beams | 228–443 ms | 1.5 ms | 210 | 3.5 s |
  | Highlight | 42–60 ms | 1.7 ms | 129 | 2.1 s |
  | ColorShift | 140–360 ms | 1.9 ms | 188 | 3.1 s |

  Parsing one frame back with `rich.Text.from_ansi` costs another 2–3.6 ms.
- **Textual's animation**: `Widget.animate`/`styles.animate` (offset, colour,
  background, opacity, size), driven by the App's animator at
  `App.frame_interval` (1/144 s in the fork). Animating colour, background or
  opacity re-renders the node **and every descendant** each tick
  (`RenderStyles._refresh`); opacity also disables the fork's plain-strip fast
  path. Offset costs a layout, not a re-render. Textual has nothing called
  "effects".
- **Toad's own animations today**, each with its own clock and visibility rule:
  `Throbber` (rainbow sweep, `auto_refresh` 1/15 s, paints only when in the
  compositor's visible set), `BusyRows` (sidebar spinner, one `set_interval` at
  the `spinner_frames_per_second` setting, paint-only), `TurnActivity`
  (elapsed clock, 1 s), Textual's `LoadingIndicator` (1/16 s),
  `future_text.py` (per-frame blend), and Textual's scroll animation.

### Where each fits, and how it renders without blocking the loop

| Effect | Fits | How it renders | UI-thread cost per frame |
|---|---|---|---|
| Theme-coloured activity sweep | the busy throbber | The gradient row for a width is computed once per theme and width; each frame slices it by time. | one cached slice (measured below) |
| New-message highlight | the newest message's bar and divider | The worker that prepares the fragment's rows also prepares N (≈8) styled variants of its first rows, from accent to the role colour. A frame picks the variant for the elapsed time. | none beyond painting the rows already shown |
| Startup splash (TTE Decrypt/Print/Beams) | the empty first screen while history loads | Build the effect and all frames in a render worker process (off the UI thread and its GIL), converting TTE's character state straight to segments in the worker (no ANSI re-parse). The UI plays back finished strips. | one widget paint |
| Tab or panel transition (TTE Wipe/Slide or Textual offset) | tab switch, sidebar | A one-row wipe on the tab bar, or Textual offset animation. Never opacity or background on a container. | one row, or one layout per tick |

Rules every effect follows:

1. **An effect is a function of time.** It reads the clock when it paints;
   it holds no frame counter. A skipped tick shows the right state next tick.
2. **One animation clock.** One owner in the neutral layer runs the frame
   cadence for every running effect (replacing the per-widget timers above),
   ticks only while something is animating, and paints only effects that are
   visible.
3. **Input first.** The clock skips a tick while input is waiting in the App
   queue or a scroll or tab switch is laying out, and caps effect work at a
   per-frame budget (2 ms); over budget, effects drop to their final state.
   Scrolling and typing therefore never wait behind an effect.
4. **Precompute off the UI thread.** Anything costing more than a slice or a
   lookup per frame (TTE frames, gradients over many cells, variants of
   prepared rows) is built in the render workers, like transcript rows today.
5. **Settings.** Effects follow Textual's `animation_level`
   (`TEXTUAL_ANIMATIONS`) and a Toad setting; "none" shows final states.

## 5. The refactor

### Target

Neutral layer (no Textual, no Rich):

- `toad/colour_scheme.py`: `Rgb` (with its `#rrggbb` codec), `TerminalPalette`
  (ANSI 0–15, foreground, background, cursor), `ColourScheme` (each semantic
  colour, `dark`, and its terminal palette), the `ThemeColour` family
  (foreground, muted, primary, secondary, accent, success, warning, error),
  `ColourDepth` (24-bit, 256, 16) with its one decision, and Toad's default
  dark palette (Dracula).
- `toad/wal_palette.py`: pywal's file format, decoded once into a palette.
- `toad/line_blocks.py`: each `LineRole` declares its `colour` (and `italic`).
  A new role states its colour where it is declared.
- Later: the effect descriptions and the animation clock (section 4), and the
  catalog of schemes Toad offers (decision D2).

Textual backend:

- `toad/textual_colours.py` `TextualColours`, held by the App: the colour depth
  handed to the Console, a scheme registered as a Textual `Theme`, each theme's
  terminal palette as the Rich `TerminalTheme` ANSI colours map to (the App's
  `ansi_theme`), pywal's file followed by watchdog, and the line styles
  resolved once each time Textual rebuilds the theme's CSS variables.
- `LineTheme.of(variables)`: resolves every declared `ThemeColour` from the CSS
  variables; muted is the 60% blend in true colour and `dim` in ANSI themes.
- Consumers read `app.colours.line_theme` and listen to
  `theme_changed_signal` (published after the variables are rebuilt), instead
  of each caching its own.

### Copies deleted (first increment)

- `DRACULA_TERMINAL_THEME` and its assignment in `on_load` (`app.py`).
- The role → colour table in `LineTheme.from_app`; `from_app` itself.
- `TranscriptPage._theme`/`_line_theme()` and `LineMarkdown._theme`/
  `_line_theme()`, and the extra `LineTheme.from_app` in `prepare_fragments`.
- The `theme.secondary or theme.primary` fallback (Textual's generated
  `secondary` already defaults to primary).
- Rich's colour-depth detection for Toad (the App now asks Toad).

### Still to migrate (next increments, no decisions needed)

1. "Is the theme ANSI?": one answer, `app.native_ansi_color`, for the 4
   `current_theme.ansi` and 4 `startswith("ansi-")` sites; the patch key
   `(ansi, dark)` built once by the colours owner (4 sites).
2. Syntax theme: one choice derived from the scheme's darkness and ANSI-ness
   (3 sites plus `file_kind.py`).
3. The worker console's hard-coded `"truecolor"` reads the depth owner.
4. Selection style resolved one way.
5. Hard-coded CSS colours: `#ad8bf5` → `$accent`; `white`/`blue` → theme
   variables; keep the `:ansi` twins (they are how ANSI themes stay readable).
6. Pickled `Style._hash` in task inputs: clear it at the task boundary as
   results already do.
7. Live widgets and committed lines draw dividers differently
   (`MessageDivider` muted for every role, line dividers in the role colour).

### Edits a new case needs

| Case | Before | After |
|---|---|---|
| A new theme source (pywal) | 5 sites in 4 files: a decoder; a hand-built Textual `Theme` in the App; the hard-coded `ansi_theme_dark` in `on_load`; and the three `watch(app, "theme")` consumers, which do not fire when a theme's colours change under the same name | 2: a decoder to `TerminalPalette`/`ColourScheme`, and one `colours.register(scheme)` (plus a watcher if the source changes live) |
| A new backend (PyQt) | Re-derive 4 facts held in Textual code: the role table, the muted rule, the default palette (a Rich type), and the pywal decoding (did not exist) | 2 functions: scheme → its palette type, `ThemeColour` → its colour; roles, palettes, pywal and depth are reused |
| A new line role | 2 files: the role class and a row in `LineTheme.from_app` | 1: the role class with `colour = ...` |
| A new semantic colour | n/a (roles named Textual theme fields directly) | 1 class in `colour_scheme.py`; 0 backend edits when Textual has a variable of that name |

## 6. Decisions for Tristan

Each has a default I will follow unless told otherwise.

- **D1. True colour in `st`.** `st` shows 24-bit colour but does not say so, so
  Toad (and every Rich/Textual app) uses 256 colours.
  Options: (a) export `COLORTERM=truecolor` for `st` (st's `config.h`, or your
  shell profile when `TERM` starts with `st`); (b) a Toad "colour depth"
  setting (auto/24-bit/256/16) that overrides detection; (c) treat `TERM=st-*`
  as 24-bit inside Toad.
  **Default: (a).** It fixes every program at its source, needs no Toad code,
  and keeps one authority (the environment). (c) is a lookup table of terminal
  names that would go stale.
- **D2. Toad's theme catalog.** Textual's 20 built-in themes live in Textual;
  a PyQt frontend would not have them.
  **Default:** Toad's catalog becomes neutral: `ansi-dark`, `ansi-light`,
  `wal` (when pywal has written a palette), and the built-in themes'
  definitions moved into neutral `ColourScheme`s (Textual registers them from
  there; Toad stops offering Textual's copies).
- **D3. Which pywal colour is which.** **Default:** the same slots the ANSI
  themes use: primary = colour 4 (blue), secondary = 6 (cyan), accent = 5
  (magenta), success = 2, warning = 3, error = 1, background, foreground and
  cursor from `special`. pywal palettes often repeat 1–6 in 9–14, so accent
  differs from success only when colour 5 differs from colour 2.
- **D4. Default theme.** **Default:** stay on `ansi-dark` (follows pywal live
  with no file reading) and offer `wal` (true colour, smooth shades). Switch
  the default to `wal` after D1 makes true colour real in `st`.
- **D5. Effects library.** **Default:** add `terminaltexteffects` (pure Python,
  MIT, no dependencies) for the startup splash only, built in render workers.
  Package changes go through review, so this waits for your yes.
- **D6. Which effects, in order.** **Default:** (1) theme-coloured activity
  sweep, (2) new-message highlight (≈400 ms fade from accent), (3) startup
  splash while history loads, (4) tab wipe. Each must hold frame p95 and keep
  every wait at or under 16 ms in the scroll scenario before it is published.
- **D7. User and agent colours.** The committed history drew the user in the
  primary colour and the agent in the secondary, the reverse of the live
  widgets, so a sent prompt changed colour when committed. **Implemented
  default:** follow the live widgets (user = secondary, agent = primary). Say if
  you want the reverse; it is one line per role.

## First increment (implemented)

Commits on `main`: see the report at the end of this section.

- Neutral: `toad/colour_scheme.py`, `toad/wal_palette.py`; roles declare
  their colour in `toad/line_blocks.py`.
- Textual backend: `toad/textual_colours.py`; `LineTheme.of`; the App asks the
  colours owner for its colour system, its ANSI palette and its line styles.
- Textual fork: `App.get_color_system()`.
- Fixed on the way: muted and thinking text are dimmed under ANSI themes; a
  committed user prompt keeps its live colour (D7).
- A `wal` theme appears in the theme setting when pywal has written
  `colors.json`, and follows `wal -i` live.
- First effect on the neutral model: `toad/effects.py` `ACTIVITY_SWEEP`, a
  `GradientSweep` of primary → accent → secondary, one pass a second at
  15 frames a second. The throbber paints it from the theme's variables; the
  gradient row is built once per width and colour set and sliced by time. True
  colour blends cell by cell; ANSI steps. The hard-coded six-colour ANSI
  rainbow is gone. Not yet done from section 4: the single animation clock and
  yielding to input (the throbber keeps its own 15 fps timer and paints only
  while visible, as before).

Evidence:

- `tests/test_colour_scheme.py` (12 tests): decoding pywal's file exactly,
  rejecting what pywal does not write, `PYWAL_CACHE_DIR`, depth per terminal
  (each in its own process, as terminfo is read once), every role resolved in
  all 20 built-in themes, muted dimmed in ANSI and blended in true colour.
- Headless run of the real `ToadApp`: switching to `wal`, then rewriting a copy
  of `colors.json` with new colours while the app runs, applies the new primary
  and secondary within 1 s with no restart.
- Real app, real screens: `toad` in `st` on an isolated display, opening a
  fork of the saved `perf-base-20261009` session, in the `wal` theme with
  `COLORTERM=truecolor`. History, the live tail, the activity sweep, End and
  tab return all draw in the pywal colours (scenario screenshots
  `theme-wal-*/{loaded,pageup,end,tab-return}.png`). Rewriting a copy of
  `colors.json` (`PYWAL_CACHE_DIR`) with another cached pywal scheme while the
  app runs recolours the whole screen within 2 s, no restart. `ansi-dark`
  screens are identical to the published build except the user and agent
  colours (D7).
- Scroll scenario (`tools/performance/scroll_scenario.sh`, display `:147`, no
  channel message), interleaved, published runtime
  `toad-27f455803-textual-1cae780a7-core-ddb4c047d` against a scratch copy of
  it carrying this work. Run 1 of the candidate is the scheme work alone;
  later candidate runs include the sweep.

  | Build | Frame p95 (ms) | Frame p99 (ms) | Input-to-paint p95 (ms) | Worst wait (ms) | Waits over 16 ms | Screen checks |
  |---|---|---|---|---|---|---|
  | Published, `ansi-dark` | 9.7, 9.3, 10.1 | 17.7, 18.3, 16.9 | 8.5, 8.9, 8.3 | 12.2, 12.8, 11.2 | 0, 0, 0 | pass |
  | Candidate, `ansi-dark`, 256 colours | 9.1, 9.3, 9.6 | 19.9, 17.1, 15.9 | 7.9, 8.1, 8.9 | 13.1, 14.2, 10.7 | 0, 0, 0 | pass |
  | Candidate, `wal`, 24-bit | 9.3, 9.2, 10.5, 9.6 | 17.0, 18.4, 17.9, 17.1 | 8.2, 8.7, 9.7, 9.0 | 14.5, 12.8, 15.2, 15.4 | 0, 0, 0, 0 | pass |

  Within the run-to-run noise recorded in `scroll-series.md` (about 1 ms of
  p95). The `wal` worst waits sit 1–3 ms above the others, all under 16 ms;
  four runs do not separate a cause.
- Per-frame cost of the activity sweep in the real app (fourth `wal` run,
  `TRACE_CALLS`, 24-bit blended gradient): `ThrobberVisual.render_strips`
  0.023 ms median, 0.031 ms p95 over 199 painted frames; 0.71 ms once, the
  first time a width is drawn (the gradient row). Its timer callback
  0.069 ms median, 0.13 ms p95 (230 calls). About 1.4 ms per second of busy
  time at 15 fps.
- One published-runtime run (the first `pub-2`) never started: a candidate
  run had left `"theme": "wal"` in `~/.config/toad/toad.json` (the app writes
  its whole settings snapshot when it exits), and the published build has no
  `wal` theme, so it raised `InvalidThemeError`. The file was restored from its
  backup (checksum `5f8ef5a4…` verified after every later run) and the runner
  now restores it after each app exits. The run was repeated.
