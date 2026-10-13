# Toad theme audit — 2026-10-13

Scope: the live `wal` theme (Tristan's default; no `theme` key in `toad.json`), measured on
the published runtime `toad-f9107b8ab`, rendered in real `st` on an isolated Xvfb display
against a fork of saved session `perf-base-20261009`. Contrast computed from the theme
variables the app itself resolves (same code path, true colour), composited and rated with
WCAG relative luminance. Screenshots: `/home/ts/.cache/agent-scratch/toad-theme/shots/run1/`.

## 1. Owner map

Fact: every semantic colour and effect is declared in the standalone `ui-theme` package
(git rev `71d088ec`); it imports nothing from Toad, Textual or Rich. Reality matches
Tristan's direction, with these deviations:

| What | Owner | Where reality differs |
|---|---|---|
| Semantic roles (foreground, background, primary, secondary, accent, success, warning, error, surface, panel, boost, muted) | `ui_theme.scheme` (`ThemeColour` classes, `scheme_of_palette`) | Clean |
| Schemes catalogue (textual-dark, nord, dracula, wal, …) | `ui_theme.catalog.SCHEMES` | Clean |
| Effects and the animation clock (`GradientSweep`, `Fade`, `Wipe`, `PlayedText`, `AnimationClock`) | `ui_theme.effects`, `ui_theme.clock` | Clean |
| Textual adaptation (themes, palette, line styles, effect painting, one timer) | `src/toad/textual_colours.py` (`TextualColours`, `Animated`) | Clean — the only adapter |
| Transcript role → colour mapping | `toad.line_blocks.LineRole.colour` → `ui_theme` classes; styles resolved once per theme in `LineTheme` | Clean |
| Widget/screen CSS | all `.tcss` and `DEFAULT_CSS` use `$variables`; no hex literals | Clean |
| ANSI stream decoder (SGR from agent output) | `src/toad/ansi/_ansi.py` | Legitimate boundary — external input decoded once |
| **StandbyPulse (goal bar)** | should be `ui_theme` clock; instead `set_interval`-driven `styles.opacity` flips every 0.8 s | Off-owner animation mechanism |
| **future_text fade** | should be `Fade`/clock; instead `set_interval(1/60)` hand-built fade | Off-owner animation mechanism |
| **activity_spinner** | should be an effect; instead per-widget `set_interval(fps)` | Off-owner animation mechanism |
| **Mandelbrot demo gradient** | 12 literal hex values in `widgets/mandelbrot.py` | Only hex literals in the tree; demo, not themed |
| Terminal-palette reads (`ansi_blue`, `ansi_default`, …) in CSS | `ui_theme` palette via Textual variables | Same colour twice under two names (`ansi_blue` == `$primary` under wal): two authorities for one colour |

## 2. Rendered contrast (wal scheme, background `#0B0B0D`)

Limits: 4.5:1 text, 3:1 UI marks. Effective colours composite alpha over the painted background.

### Failing pairs

| Pair | fg | bg | Ratio | Limit | Where |
|---|---|---|---|---|---|
| Sidebar focused row (ansi_bright_white on ansi_blue) | `#C3C3C3` | `#90A827` | **1.52** | 4.5 | `comms_sidebar.py:190` — the selected thread/channel row |
| Sidebar hover row (ansi_white on ansi_bright_black) | `#C3C3C3` | `#888888` | **2.01** | 4.5 | `side_bar.py` inverse rows |
| Disabled text (38 % alpha) | `#515152` | `#0B0B0D` | **2.48** | 4.5 | disabled controls |
| Input placeholder / dim detail (40 % alpha) | `#555556` | `#0B0B0D` | **2.62** | 4.5 | `main.tcss:269`, `side_bar.py:215` |
| Message-area text selection | `#ABABAC` | `#4D591A` (`#90A8277F`) | **3.67** | 4.5 | `screen-selection-background` |
| Goal-bar top border (`$secondary 30 %`) | `#2A2C30` | `#0B0B0D` | **1.44** | 3.0 | `goal_bar.py` DEFAULT_CSS |
| Row side-rules (`$primary 30 %`, `50 %` of `secondary 15 %`) | — | `#0B0B0D` | **1.16–2.60** | 3.0 | `main.tcss`, `toad.tcss` |
| Error-row border (`$error-muted`) | `#2F2B2A` | `#0B0B0D` | **1.40** | 3.0 | `main.tcss:189` — the only mark distinguishing an error row |
| Success-row border (`$success-muted`) | `#2B3214` | `#0B0B0D` | **1.47** | 3.0 | `main.tcss:176` |
| Scrollbar thumb on gutter | `#39430F` | `#000000` | **1.98** | 3.0 | `scrollbar` variables |
| Muted text on surface | `#757576` | `#1E1E1E` | **4.28** | 4.5 | panel content |
| Footer key hint bg vs background | `#26282C` | `#0B0B0D` | **1.33** | 3.0 | `toad.tcss:114` |

### Passing but fragile

- `muted` text on background: **4.55** (limit 4.5) — any dimmer wallpaper breaks it.
- Status text colours `text-success #A5B370` 8.69, `text-error #AEA5A0` 8.14 — pass, but see §3.

## 3. Meaning collisions (wal-specific)

`scheme_of_palette` maps roles to fixed ANSI slots: error→color1, success→color2,
warning→color3, primary→color4, accent→color5, secondary→color6. Tristan's wallpaper
palette is muted moss, so the status roles collapse into greys:

- `error #857870`, `accent #8F9466`, `secondary #797E87`, `warning #77866F` — four
  "different" roles within a handful of grey-green steps; error text `#AEA5A0` is within
  ~4 % luminance of body text `#ABABAC`. An error is distinguishable only by its words.
- `success #778D27` ≈ `primary #90A827` — near-duplicate hues.
- One colour, many meanings: `#90A827` is simultaneously `$primary`, `border`,
  `block-cursor-background`, `screen-selection-background`, `scrollbar-active`,
  `ansi_blue` (focused row) and the tab underline.
- One meaning, many colours: "selected row" is drawn four ways (comms focus inverse,
  side_bar inverse, screen-selection tint, block-cursor pair); "dim text" is drawn at
  six ad-hoc alpha levels (`auto 60 %`, `38 %`, `$text 40 %`, `$text-muted 40 %`,
  `$text 70/80 %`, `$foreground 4–10 %` backgrounds).

## 4. Proposed role palette (each role defined once, widgets read roles only)

Text levels (owned by `ui_theme` `MutedColour`-style derivation, never raw alpha):

| Role | Definition | wal now | on `#0B0B0D` |
|---|---|---|---|
| `text` | foreground @ 87 % | `#ABABAC` | 8.57 |
| `text-muted` | background→foreground blend 0.6 | `#757576` | 4.55 → raise to 0.65 ⇒ ~5.2 |
| `text-faint` (disabled only) | blend 0.45 | `#5F5F60` | ~3.2 (exempt: disabled) |
| `placeholder` | = `text-muted` (kills `$text 40 %`) | — | 4.55 |

Marks and status (selection/status read one role each):

| Change | Before | After |
|---|---|---|
| Comms focused row: `$background` text on `$accent`/`$primary` bg (not bright_white on ansi_blue) | 1.52 | **6.18 / 7.30** |
| Message selection: text on selection bg 35 % (or full `$accent` + dark text) | 3.67 | **5.02 / 7.32** |
| Sidebar hover: `$background` on `$accent` (same pair as focus) | 2.01 | **6.18** |
| Status-row borders: full role colour (`$error`, `$success`, `$secondary`) | 1.40–1.47 | **4.61 / 4.65 / 4.82** |
| Goal-bar border, side-rules: full `$secondary` or `$secondary-muted`-derived mark ≥ 3:1 | 1.44 | **4.82** |
| Scrollbar thumb: `$secondary` on `scrollbar-background` | 1.98 | **5.15** |
| Footer key bg: `$secondary 25 %` → `$surface` | 1.33 | pass |

The status-colour collapse cannot be fixed in Toad: the wal role→slot mapping lives in
`ui_theme.scheme.scheme_of_palette` (the owner). Proposed there: pick status slots by
chroma and hue separation from the wallpaper palette, and synthesize a distinct error hue
when the palette has none (it stays derived from the palette, so pywal still works).
Toad-side changes are only role-strength and role-choice fixes in CSS.

## 5. Animations

Owner: `ui_theme.effects` + `AnimationClock`; Toad consumes through `Animated`/`run_effect`
with one Textual timer in `TextualColours`. Existing: `ACTIVITY_SWEEP` (throbber, runs while
busy), `NEW_MESSAGE` fade (message divider, 0.4 s @ 30 fps — over the 200 ms target; halve),
`TAB_WIPE` (session tab underline, 0.25 s), `PlayedText` (splash). Candidates (new-message
arrival in the channel view belongs to toad-ui-2 — coordinate, no second implementation):
row expand/collapse, status change, focus change — all as clock effects, paint-derived, each
≤ 200 ms, off by one setting (`animation_level == "none"` already disables the clock).
Deviations to fold into the owner: StandbyPulse, future_text, activity_spinner (§1).

## Method note

Captures: fork `perf-base-20261009` → real `st` on `:147` (Xvfb, no WM), published runtime
`toad-f9107b8ab`, true-colour `wal` (copy of `~/.cache/wal/colors.json` via
`PYWAL_CACHE_DIR`), `toad.json` restored byte-identical afterwards, fork stopped and
deleted (147 MB freed). Views captured: DM tail/history/End, sidebar expanded + selection
drag, channel/IRC view with saved-sessions popup and roster, collapsed/expanded sidebar,
tab bar. Not captured: goal bar (fork has no goal; setting one for another thread needs its
agent started), tool rows and error rows (none in the fork's history) — their pairs are
computed from the CSS/theme resolution above, which is exact for these variables.