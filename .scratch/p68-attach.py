"""Attach the existing observation to the already-ready, owned real UI."""
import os
import __main__
from functools import partial
from textual.app import App

if os.getpid() != 608167:
    raise RuntimeError('P68 frontend process changed')
app = App.running_app()
app.schedule_from_thread(partial(app.run_worker, __main__.observe(app),
    name='p68-live-observation', exit_on_error=False))
