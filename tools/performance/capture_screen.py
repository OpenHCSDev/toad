"""One-shot screenshot via Textual's own export API, including unmapped windows."""

def capture(*, expected_pid, output_prefix):
    import asyncio
    import json
    import os
    import time
    import traceback
    from textual._context import active_app

    prefix = str(output_prefix)
    try:
        if os.getpid() != expected_pid:
            raise RuntimeError("Unexpected capture process")
        app = active_app.get(None)
        if app is None:
            for task in asyncio.all_tasks():
                app = task.get_context().get(active_app, None)
                if app is not None:
                    break
        if app is None:
            raise RuntimeError("No app context")

        def export():
            started = time.monotonic_ns()
            try:
                with app._context():
                    svg = app.export_screenshot()
                    fd = os.open(prefix + ".svg", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as output:
                        output.write(svg)
                    app.screen.refresh()
                receipt = {"pid": os.getpid(), "export_ms": (time.monotonic_ns()-started)/1e6,
                           "mode": app.current_mode, "svg": prefix + ".svg"}
            except Exception:
                receipt = {"error": traceback.format_exc()}
            fd = os.open(prefix + ".json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(receipt, output)

        asyncio.get_running_loop().call_soon(export)
    except Exception:
        fd = os.open(prefix + "-error.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump({"error": traceback.format_exc()}, output)
