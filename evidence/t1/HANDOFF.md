# T1 settings complete source handoff — PR119

Branch refactor/t1-settings-20260928 from Toad6662485. Own persistent tree /home/ts/wt/toad-t1-settings-20260928. PR243 source/package retained for Lovelace; no overlapping native edits or live changes.

## Implemented

- SettingsNode / SettingKind / SettingsGroup own one typed preference tree. Boundary parsing uses existing Comms FieldCodec; choice families use existing DeclaredFamily. No duplicate shared codec/registry package.
- Boolean, integer/number with shared Bounded capability, string/text/path and declared choice kinds own parsing, constraints, editors. Textual event owners bind directly to a declaration; screen has no kind or dotted-key dispatcher.
- All current production settings reads/writes and test callers migrated to typed attributes. Effects are referenced on field declarations; app dispatches the typed change and publishes it. Current sidebar/recovery/launcher listeners compare declaration identities.
- Expansion policy owns decisions; Both composes Success/Fail. Sessions bar, notification focus policy, diff mode/wrap, loading widget and scrollbar/theme choices own current behavior. Theme members derive from Textual's current theme owner, with no second authored theme roster.
- Deleted settings_schema.py, Schema/SchemaDict/Setting/INPUT_TYPES, Settings.get/set/get_setting, schema_to_widget and app/store setting_updated dispatch. No aliases or old constructors retained.
- Durable preferences retain exact current keys. Most keys derive from attribute paths. Existing mixed underscore spellings are declared once using the same field-owned wire_name principle as Comms FieldCodec; they are not renamed or recognized through a second reader. Actual saved anon_id/sidebar/ui document loads and serializes exactly unchanged. No cutover tool or live writes needed.

## Evidence

- settings-sixth.log: actual Toad on_load with an owned copy of today's saved preferences, mounted SettingsScreen, all kinds and bounds, editing/validation/effects, test-only new kind+group member, save/reopen, original file unchanged: PASS. No agent or provider launched; mount event suppresses ordinary launcher startup.
- guards.log: deleted API/string-read AST guards PASS. Unrelated ACP protocol SchemaDict is an external protocol owner, not the deleted settings schema.
- names.log: current source name resolution guard PASS; full source compile passed.
- Earlier failed local harness runs retained in owned evidence directory; CSS subclass path, widget active-app context and Textual mount-default handling were corrected. They are not passes.

## Final acceptance and caller contract

- settings-final.log: actual saved preferences load unchanged; every kind parses/rejects/creates an editor; bounds and nonfinite number rejection; mounted footer/column/theme effects; new kind/group member; save/reopen; original untouched: PASS.
- visibility-current.log: stopped/archived menu values persist, roster follows settings, archived DM opening does not restart its owner: PASS.
- selection-current.log: selection/disclosure and manual tool expansion state preserved: PASS.
- diff.log: native patch live/replay display, hunk positions and bounded automatic expansion: PASS.
- recovery-current.log: default-off, post-paint read, unavailable/rename/re-enable routing: PASS. Fixed the pilot's hardcoded third-read wait to await the actual renamed-owner result; all behavior assertions retained.
- permissions.log: actual mounted diff permission UI and stale/cancelled answer fencing: PASS.
- guards-final.log: no old schema/type APIs or string access/change routing: PASS. New owner modules/guards pass Ruff; all source compiled.

A remaining SideBar listener still unpacked the deleted tuple event in the first two consumer runs; it now consumes PreferenceChange and the reruns pass. Those initial failures are not counted as successes. Editor creation uses the real Textual active-app context, and the pilot's mount event prevents unrelated ordinary launcher startup.

Current contract: app.settings is ToadSettings; reads and writes are typed attributes. app.settings_changed_signal publishes PreferenceChange(field, value), and field is the exact SettingKind descriptor declared by its group. Widgets bind a BoundSetting, never a dotted lookup. No saved representation changed and there is no one-shot cutover tool. Only the root document owns change tracking and notification state.

Source tally before this receipt: product1154 added/1124 deleted; tests303 added/23 deleted. Net product growth is30 lines because the previous central branches became complete kind/choice/widget owners; test growth adds the previously missing family, extension and mounted persistence/effect acceptance. No tests protecting deleted coercion/schema internals existed; retained high-level consumer tests were migrated.

Parent owns paired current core/Toad installation and merged-tree suite. Existing FieldCodec/DeclaredFamily are imported directly from the installed paired current core; no copied shared abstraction or core source change is needed. Source acceptance is complete; live activation is not claimed.

Scope excludes T2/T3/T4 scheduling/ACP/rendering work. T3 follows T2. Preserve native243 package until combined capacity acceptance is complete.
