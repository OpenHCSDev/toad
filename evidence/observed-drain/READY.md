# Ready: typed drain attention

Pair: core https://github.com/OpenHCSDev/agent-comms/pull/280 and Toad https://github.com/OpenHCSDev/toad/pull/128.

Core pinned fc2df0203cf006aaf0eae2fdd7217d2b293654ee, including main afe0688a; Toad main 08d464b (T4) incorporated. Textual retained at 16ede007c34bec893b2dbedb3999223381129678.

Noneditable installed Toad wheel: `python -m pytest tests/observed_thread_activity_pilot.py tests/session_details_pilot.py --basetemp .artifacts/final-pilots -q`: **2 passed in 45.95s**. Source modules are not injected into PYTHONPATH. Pilot follows actual core Activity persistence through ACP reader into mounted Toad conversation, Session details and DM, including a subsequent ACP Ready event and recovery to Ready. Core's own 17 installed tests separately create actual missing and drifted runtime schemas and exercise background InputDrain, without a mocked drain for these schema failures.

Initial pilot timeout was a fixture attachment bug: its coordination fact belonged to a temporary app that it subsequently replaced. The test now installs the fact on the mounted app. Initial failure receipt retained.

No remaining diagnosed source/caller blocker; parent owns merge/install. No live root mutation, provider calls or CI wait. Disposable pilot roots/wheels removed after preserving receipts.
