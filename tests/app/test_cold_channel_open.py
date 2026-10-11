"""Opening a channel for the first time shows its history and an input that accepts text, not only a loading frame."""


async def test_each_cold_channel_opens_to_its_history_with_a_ready_composer(workspace):
    me = workspace.project.name
    workspace.thread(me, "fixture", running=True)
    comms = workspace.comms
    targets = [f"#scene-{index}" for index in range(6)]
    for target in targets:
        comms.channels.create_tag(target.removeprefix("#"))
        comms.messaging.send(me, target, f"Scene history marker {target}\n" + "message body " * 20)

    async with workspace.app(size=(120, 40)) as ui:
        owner = ui.selected_tab
        for target in targets:
            await ui.open_channel(target, actor=me)
            await ui.until_shows(f"Scene history marker {target}")
            await ui.until_agent_ready()
            await ui.select_tab(owner)
