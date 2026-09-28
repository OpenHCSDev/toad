# Migrate current Toad export caller after core compatibility deletion

Use concrete scope and limit declarations; decode the format once at the Select boundary. Remove every use of core export forwarding constructors and enum-style constructor. Pin core to current merged main including agent-comms PR157 diagnostics and PR158 export deletion; Textual remains latest merged 4fa6a9c.

Mounted tests/main_menu_transfer_pilot.py passed against the updated core and Toad sources: invalid-channel feedback, actual JSONL export with expected message, and stopped-thread import with saved history. Core paired change passed 103 focused tests. Current file format is unchanged. Parent owns paired installation and live activation.
