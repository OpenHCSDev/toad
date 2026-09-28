Pair with core PR280 so background inbox failures remain visible in Toad instead of being overwritten by ACP Ready.

- Existing observed activity carries typed attention independently of busy; failure is not represented as a running turn.
- Existing Session details summary gets the warning text and Needs attention styling; DM status shows the same diagnostic.
- Recovery clears the warning through the same owner activity projection.
- Correct the mounted pilot to attach its coordination fact to the actual mounted app before observing it (the previous fixture lost its fact when switching apps).
- Includes current T4 main 08d464b. Core pin fc2df020 includes current main afe0688a. Textual pin unchanged. uv.lock additionally reconciles already-declared main dependencies (playwright and textual-serve pin).

Evidence: installed core PR280 has 17 passing tests including actual missing/drifted SQLite -> background InputDrain -> visible diagnostic -> explicit schema restore -> Ready. Installed Toad wheel on current T4 main: **2 passed in 45.95s** (`observed_thread_activity_pilot.py`, `session_details_pilot.py`). Both native conversation and DM warning/recovery are mounted and exercised; ACP Ready cannot erase attention. No remaining diagnosed blocker. No provider calls, live root changes or CI gate.
