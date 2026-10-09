from tests.shutdown_mode_installed_pilot import main

async def test_shutdown_retires_admitted_stacks_when_unmount_removes_mode():
    await main()
