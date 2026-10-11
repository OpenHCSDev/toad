"""A channel tab goes back to the session tab that opened it, and only that one."""


def declare_owners(workspace):
    for name in (workspace.project.name, "owner-a", "owner-b"):
        workspace.thread(name, running=True)


async def two_owners_with_channels(ui):
    first = ui.selected_tab
    channel_a = await ui.open_channel("#all", actor="owner-a")
    second = await ui.new_session()
    channel_b = await ui.open_channel("#all", actor="owner-b")
    return first, channel_a, second, channel_b


async def test_a_second_owner_does_not_reuse_the_first_owners_channel_tab(workspace):
    declare_owners(workspace)
    async with workspace.app(size=(120, 44)) as ui:
        first = ui.selected_tab
        channel_a = await ui.open_channel("#all", actor="owner-a")
        assert ui.sender_of(channel_a) == "owner-a"
        second = await ui.new_session()
        channel_b = await ui.open_channel("#all", actor="owner-b")
        assert channel_a != channel_b, "A second owner must not reuse the first owner's Back view"
        assert ui.sender_of(channel_b) == "owner-b"

        await ui.return_to_owner()
        assert ui.selected_tab == second
        await ui.go_back()
        assert ui.selected_tab == channel_b
        await ui.go_forward()
        assert ui.selected_tab == second

        await ui.select_tab(channel_a)
        await ui.return_to_owner()
        assert ui.selected_tab == first


async def test_the_same_owner_reuses_its_channel_tab(workspace):
    declare_owners(workspace)
    async with workspace.app(size=(120, 44)) as ui:
        first, channel_a, second, channel_b = await two_owners_with_channels(ui)
        duplicate = await ui.open_channel("#all", actor="owner-b", owner=second)
        assert duplicate == channel_b, (duplicate, channel_b, ui.tabs())
        await ui.return_to_owner()
        assert ui.selected_tab == second


async def test_a_renamed_thread_keeps_its_channel_tab_and_the_other_owner_keeps_its_name(workspace):
    declare_owners(workspace)
    async with workspace.app(size=(120, 44)) as ui:
        first, channel_a, second, channel_b = await two_owners_with_channels(ui)
        workspace.comms.registry.rename("owner-a", "owner-renamed")
        await ui.thread_renamed(first, "owner-a", "owner-renamed")
        assert ui.sender_of(channel_a) == "owner-renamed"
        assert ui.sender_of(channel_b) == "owner-b"
        late_old_name = await ui.open_channel("#all", actor="owner-a", owner=first)
        assert late_old_name == channel_a, "A late old alias must resolve to the existing renamed view"


async def test_closing_an_owner_closes_only_its_own_channel_tab(workspace):
    declare_owners(workspace)
    async with workspace.app(size=(120, 44)) as ui:
        first, channel_a, second, channel_b = await two_owners_with_channels(ui)
        workspace.comms.registry.rename("owner-a", "owner-renamed")
        await ui.thread_renamed(first, "owner-a", "owner-renamed")

        await ui.close_tab(first)
        identities = [tab.identity for tab in ui.tabs()]
        assert channel_a not in identities and first not in identities
        assert channel_b in identities and second in identities
        active = ui.selected_tab
        late_action = await ui.open_channel("#all", actor="owner-a", owner=first)
        assert late_action == active, "A late action from a removed owner must not create a tab"
        assert channel_a not in [tab.identity for tab in ui.tabs()]

        replacement = await ui.new_session()
        assert replacement not in (first, second)
        reconnected = await ui.open_channel("#all", actor="owner-renamed", owner=replacement)
        assert reconnected not in (channel_a, channel_b)
        await ui.return_to_owner()
        assert ui.selected_tab == replacement
        await ui.select_tab(channel_b)
        await ui.return_to_owner()
        assert ui.selected_tab == second
