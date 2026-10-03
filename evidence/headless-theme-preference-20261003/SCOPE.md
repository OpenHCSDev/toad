# U2: selected theme is preference data; catalog belongs to the native editor

Source base: Toad main 8840d35ce8364f2b1c2cbbeac3c90ef6aa76be76.

The existing ThemeChoice eagerly derives classes from Textual BUILTIN_THEMES. UiSettings.theme decodes its default at declaration time, and ChoiceSetting decodes the same catalog again when loading saved preferences. This makes loading the durable preference tree depend on the installed frontend catalog.

Reuse ThemeChoice as the original theme preference declaration over StringSetting's existing load/set/FieldCodec behavior. Preserve the durable JSON string exactly; a selected name is neither a copied Textual Theme object nor a second theme catalog. The native SettingsScreen interprets that declaration through its existing MroProjection and obtains options from the actual App.available_themes. The original ChoiceEditor accepts original options and owns editing for both nominal policy choices and theme names. Theme effects pass the original stored name to App.theme. Delete native_themes and all old class-valued theme consumers together. No compatibility reader/alias, no duplicated catalog, no new frontend framework.

Source mapping uses existing refactor-audit Package across src/toad and tests: 289 and 392 parsed modules; zero omissions. One ThemeChoice definition, one eager Textual catalog import, one preference declaration/decode, one native effect, four existing fixture imports. Read SettingsNode/SettingKind/StringSetting/ChoiceSetting load/edit/codec, SettingsScreen and ChoiceEditor consumer semantics; lexical AST does not prove dynamic MRO behavior.

Heisenberg explicitly granted native_themes, preferences/settings/setting_effects/settings editor; viewport/body/preparation/paint remain his. Source only until the coherent family is implemented, then one batched focused check and the affected installed settings App path on an explicitly released existing holder. No package loan now, no new checkout/environment/native copy/provider call. CI deferred. This closes the theme family, not all U2 or the full frontend programme. 406 is frozen independently.
