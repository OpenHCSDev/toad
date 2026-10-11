"""The stylesheets Toad ships, for a test's ToadApp subclass.

Textual resolves ``CSS_PATH`` against the file that defines the class, so a
subclass in a test module must name the installed files itself.
"""

from importlib.resources import files

INSTALLED = [files("toad").joinpath(name) for name in ("toad.tcss", "screens/comms.tcss")]
