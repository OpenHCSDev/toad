"""Textual-facing: a saved tab whose target is gone is dropped at startup, not a crash."""
from toad.db import DB, UNSCOPED_TABS
from toad.tab_identity.kinds import AcpTab


async def test_a_saved_tab_without_its_session_is_removed_at_startup(workspace):
    stale = AcpTab(999)
    database = DB()
    await database.create()
    # Saved before tabs had a scope: the local Core reads it as its own and prunes it.
    await database.tab_roster((UNSCOPED_TABS,), (stale,))
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        await ui.step()
        assert stale not in app.tab_order
        assert stale not in [row.identity for row in await database.tab_list(app.tab_order.scopes)]
