# Settings native projection owner

Reason from source; implement one complete family; validate last.

The existing SettingsNode/SettingKind/Group model constructs Textual forms,
Content descriptions and editor widgets, and NumericSetting retains Textual
input-kind names. The actual model owner already supplies declaration discovery,
BoundSetting, parse/set/ranges, choice membership, persistence and notifications.
Those facts remain original; no independent frontend settings values or forms.

Existing SettingsScreen and Input/Text/Boolean/Choice editors own native creation.
Move ALL native form/widget/description factory behavior there and migrate both
real consumers (screen + old settings pilot). Delete model form/widget/Content
and native input-kind paths in the same batch; preserve style, validation,
initialization, recursive editable groups, extension via inherited descriptors,
focus/commit and durable saved values.

The existing ContextProjection already supplies a nominal projection's returned
value, unlike MroDispatch's event-identity replacement contract. Promote that
SAME class as shared core projection behavior and migrate all existing context
subclasses plus SettingsScreen. No new class/registry/probe-dispatch copy or
compatibility export. This is a shared behavior owner, not a cosmetic relocation.

Heisenberg grants these schema/editor/form methods; CSS, geometry, frame,
viewport, settings effects and native theme policy excluded. Original theme and
preferences dependencies remain; no full U2/U4/U5 completion claim.

AST uses existing refactor-audit Package over production/tests before/after, no
silent omissions. Read actual dispatch and descriptor contracts before edits.
Final one existing settings_tree_pilot installed App journey with original saved
settings/control/edit/effects/save/reopen and subtype extension; no provider,
new environment, public settings mutation or repeated catalog/native gate.
Receiver owns packaging; useful current release does not wait on this draft.


## Working whole-family change

The original ContextProjection becomes MroProjection in core/projection.py;
NativeDetail and SegmentNodes migrate, and SettingsScreen inherits that SAME
returned-value dispatch behavior. No second handler selection/registry or class.
Model descriptor forms/widgets/descriptions are deleted. SettingsScreen owns all
Group/scalar/Text/Boolean/Choice/Path/numeric forms and native help. Its recursion
borrows group/title context, never probes private group declaration fields.

ChoiceEditor obtains membership from its original BoundSetting.kind.family;
its duplicate family argument is deleted. InputEditor also deletes copied Number
min/max validators: native Function asks original kind.parse_text. This preserves
native validation feedback while the original field owns range/parse decisions.
No scalar limits are copied into a competing native validator. Numeric input
keyboard grammar remains a Textual concern, declared by native nominal handlers.

Effects, timers, choices/themes, save lifecycle and source values remain original.
The old settings journey's model.widget call and source-tree CSS path migrate to
existing SettingsScreen projection and installed resources; no alternate fixture.


BoundSetting.set_text owns parse-then-set for both InputEditor and TextEditor;
the multiline control no longer bypasses its inherited field parser. Typed
Boolean/Choice edits keep their original set(value) contract. Native Function's
boolean result is only an external UI validation projection of the same parser,
not stored state or an alternate range/codec.

## Published source checkpoint

Production fcef3086 is normally integrated with merged388 main at145a9e09.
The merge changes receiving pins/evidence only; all five production files and
the affected settings pilot are byte unchanged. Production is116 added/110
deleted lines. Source-sanity and before/after owner-consumers records live beside
this receipt:289 production modules and391 test modules, zero parse omissions.
The model has no Textual imports or native factory declarations; MroProjection
has exactly one declaration and all original consumers migrated. Lexical AST
evidence does not claim complete dynamic resolution or installed readiness.

Bohr released the retired485 codeholder after actual borrower/archive checks.
Sch is its sole package writer; ONE existing settings_tree_pilot installedApp
journey follows his matched handoff. Current334 remains live and unchanged.
No new environment, provider, Pi input or public settings mutation is needed.

## Installed fixture checkpoint

Installed02 passed in5.6758 seconds using the repository's retained saved settings
fixture: actual App/Pilot controls, ranges, initialization, effects, inherited
parser, durable save/reopen and original source unchanged. All928 installed
source assets remained equal, no owned process or private settings root remains.
No provider or Pi input. Installed01 stopped before App creation because three
old fixture ToolCall constructors lacked the official required title; all three
are corrected, product unchanged, and raw failure retained.

Exported SVG/PNG body is black and retained as a negative. This does not establish
readable physical paint. Final parent-requested actual saved user configuration
donor is pending on the same existing driver after matched390 package handoff.
No full headless, physical, provider or performance claim.
