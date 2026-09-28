# T1 settings implementation checkpoint

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

## Remaining in this draft

Affected actual sidebar visibility/recovery and tool expansion/diff consumer pilots; final strengthened kind/persistence guards and source inspection. Parent owns paired current core/Toad installation. Existing FieldCodec/DeclaredFamily are imported directly from the current installed paired core; no core source change is required by this checkpoint.

Scope excludes T2/T3/T4 scheduling/ACP/rendering work. T3 follows T2. Preserve native243 package until combined capacity acceptance is complete.
