# Toad theme audit and role-consumer change

Draft #595. The implementation preserves the chosen wallpaper palette. It changes
how consumers use existing roles, not the meaning or hue of the roles. No fixed
palette, new setting, Textual-fork edit or scroll-path edit is introduced.

## Correction to the first audit

The original variable-only contrast table was wrong in two important ways:

- Textual's `auto 60%` chooses contrast black/white. It does not mean the
  wallpaper foreground at 60%. The rendered muted text here is `#9D9D9E`, not
  `#757576`. The claimed 4.55:1 muted-text limit was therefore incorrect.
- `:ansi` rules are inactive in `wal`. The 1.52:1 and 2.01:1 ANSI combinations
  were possible terminal-palette combinations, not observed wal row colours.
  The first drag screenshot selected sidebar **text**, not a CommsRow target.

A faint decorative tint is not itself a WCAG non-text failure. Meaningful marks
and readable text are evaluated separately below. Disabled controls are exempt
from the text requirement. The later snapshots contain actual compositor segment
colours and samples, not guessed foreground/background combinations.

## Owners and source evidence

| Fact | Owner | Consumers |
|---|---|---|
| Palette, semantic colours, scheme element overrides | standalone `ui_theme.scheme`, `catalog`, `wal` | `TextualColours.theme`, transcript `LineRole.colour` |
| Backend adaptation, resolved line styles and effect painting | `toad.textual_colours.TextualColours` | CSS variables, `LineTheme`, `Animated` widgets |
| Paired selection foreground/background/text style | existing scheme block-cursor elements and Textual's generated defaults | row selection, menus, model list, navigation controls, screen/input/TextArea selection |
| Status text and marks | existing success/error/secondary/primary roles | TerminalTool, GoalBar, prompt info line, HelpPanel, scrollbars |
| Effects and animation time | `ui_theme.effects`, `AnimationClock` | `Animated`, message divider, throbber, tab underline, splash |

`ui_theme` has no imports from Toad, Textual or Rich. All theme literals remain
there; this change adds none. ANSI SGR decoding in `toad.ansi` is an external
input boundary, not theme policy. The Mandelbrot demo has its own art gradient.

Before editing, refactor-audit's AST overlay enumerated Toad and the Textual
checkout. Its `ParsedModule` machinery also parsed all 280 Toad production
modules and all 10 installed ui_theme modules with zero omissions. Relevant
inheritance: CommsRow -> ThreadStatusRow -> HoverSelection -> Static;
MenuOption -> SelectionListItem -> ListItem; ModelSwitcher -> InfoPopup;
TextualColours -> Backend + TerminalBackend. Reads covered those declarations,
CSS strings, Theme/ColorSystem, Styles.parse, PaintState and Content/DOM colour
resolution. The installed ui_theme directory is not a Git checkout, so the
Git-backed overlay cannot load it; direct parsing reused ParsedModule instead.
Runtime CSS specificity and Content's auto-colour handling needed live evidence.

### Replaced decisions

The existing owners now carry the work:

- CommsRow, ThreadStatusRow, NewSessionButton, sidebar/navigation controls,
  context menus and model selection read the same block-cursor pair. Their
  separate ANSI choices and foreground-alpha inversions are deleted.
- Menu descriptions inherit selection colour rather than forcing dim text over
  the highlighted row. Focused menus use the focused pair, not a further-dimmed
  blurred pair.
- Screen, Input and TextArea selection read that same pair in one CSS rule.
- The adapter resolves a scheme's `auto` selection foreground once against its
  paired background through **Textual's existing Styles parser and Color
  contrast behaviour**. Scheme-supplied concrete colours stay untouched.
  This deletes the consumer's need to re-evaluate `auto` against its inherited
  surface. No new palette policy or colour decoder is introduced.
- Prompt completion and TextArea placeholders read text-muted; the info line
  reads text-secondary. Blurring the prompt no longer halves readable text.
- Tool success/error borders and the goal separator use full-strength status
  roles; additional whole-row opacity and light-theme border branches are gone.
- Scrollbar thumbs use secondary, with primary for hover/active. Background
  tints remain decoration, not the only meaningful status mark.

## Real-application evidence

Plain st on private Xvfb :147, current installed entrypoint
`toad-6e05712f2-core-948fec866`, true-colour wal, fresh forks of saved
`perf-base-20261009`. Candidate runs use this draft's source on PYTHONPATH with
that installed interpreter/dependencies; they are **not an installed candidate**.
Each run uses an isolated copy of toad.json via XDG_CONFIG_HOME. User settings
were never rewritten. No new provider input was submitted. Displays closed and
all owned forks stopped/deleted, freeing each 147 MB history copy.

Actual paired cell colours, WCAG relative luminance:

| Element | Before | Draft | Evidence |
|---|---|---|---|
| Info-line status | `#585B62` / `#0B0B0D`, **2.89:1** | `#A6A9AF` / `#0B0B0D`, **8.35:1** | installed and current candidate cells |
| Menu focused item | `#0B0B0D` / `#8F9466`, **6.18:1** | `#131605` / `#90A827`, **6.83:1** | installed and current candidate physical popup |
| Loaded-history selection | old claim withdrawn; installed baseline did not load | intermediate draft `#121505` / `#90A827`, **6.89:1** | first candidate loaded-history snapshot; final adapter still needs this loaded journey |
| Scrollbar thumb | generated default `#39430F` / black, **1.98:1** (source-derived) | `#797E87` / `#0B0B0D`, **4.82:1** | first candidate loaded-history cells |
| Prompt border (focused) | `#797E87` / `#1E1E1E`, **4.09:1** | unchanged role pair | actual input box |
| Tool error border | muted role `#2F2B2A` / background, **1.40:1** (source-derived) | full error role **4.61:1** (source-derived) | no tool-error row in captured history |
| Goal separator | secondary 30%, **1.44:1** (source-derived) | full secondary **4.82:1** (source-derived) | no goal bar in captured fork |

The first candidate exposed white auto text on olive hover at **2.38:1**. That
is why the final adapter resolves the pair once; the final physical menu confirms
its concrete dark text. The final loaded-history row/selection acceptance is
not complete because of the startup failure below.

Retained evidence, owner/purpose recorded in each directory:

- `~/.cache/agent-scratch/toad-theme/roles-20261013-131035/`: installed startup
  failure and first source candidate with loaded DM/channel/history selection.
- `.../roles-20261013-131806/`: installed startup still empty after 165 seconds;
  candidate constructor failure (missing Styles.parse read_from, now fixed).
- `.../roles-20261013-132305/`: final source candidate, readable status and
  focused menu, but empty sidebar/history after 165 seconds too.

No automated tests, fixtures or synthetic apps were run. Python AST parsing,
`git diff --check`, and the actual application/physical screenshots were used.
No performance result is claimed; the fixed scroll scenario was not completed.

## Remaining gap and palette decision

The retained startup failure affects both the installed application and the
final source candidate: empty sidebar and "Saved history not loaded" after
165 seconds. It was reported to toad-ui-2 with the reproducer and these original
captures; the acceptance check is populated sidebar and saved history through
the actual installed entrypoint. Follow-up on the newer installed runtime narrowed
this to Core: the observer is alive and has delivered a revision, but
`sidebar_current` is None and three reads remain pending. Its actual stack at
65 seconds is `json.loads -> BusActivityIndex.snapshot:74 -> last_sent_timestamps
-> HistoryViews.viewer_snapshot:387 -> ObservationService.observe:460`. The
original bus is about 4 GB and an activity checkpoint exists. This demonstrates
a cold scan delaying publication; why its checkpoint is not reused is not yet
established. The trace, state and physical screenshots are retained in
`~/.cache/agent-scratch/toad-theme/accept-20261013-134203/`. This source-level
reproducer was sent to the existing Core integration owner, agent-comms-ux; no
Core or observer code was edited here. This draft cannot claim full installed/live
acceptance until that journey works and final row/selection paint is checked.

The exact product decision for a subsequent palette change is: **should wal
preserve wallpaper-selected status hues, or should error/warning/success have
standardised hues even when the wallpaper palette contains none?** Current
reversible default: preserve wal. Selecting/synthesising different hues belongs
in `ui_theme.scheme.scheme_of_palette`, not this adapter. The original moss
palette still makes several status hues similar; that is not fixed here.

Animations remain with their existing owners. Channel arrival remains toad-ui-2's
piece. NEW_MESSAGE (400 ms) and TAB_WIPE (250 ms) are declared in ui_theme;
shortening them or adding effects needs that package's change. StandbyPulse and
FutureText use separate repaint mechanisms. BusyRows already has **one shared
app timer**, not one per row as the first audit incorrectly suggested. This
contrast checkpoint does not duplicate or change any of those mechanisms.
