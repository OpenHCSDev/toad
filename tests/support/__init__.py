"""What Toad's tests share: private roots, the running app, and the questions a test asks it.

Layers (see docs/agents/TESTS.md):

- ``tests/model``: no interface at all; Core answers, line blocks, view models.
- ``tests/app``: the running app through :class:`support.ui.Ui` questions that any
  frontend could answer (visible lines, tabs, focus, keys, clicks).
- ``tests/textual``: behaviour that belongs to the Textual frontend (paint, layout,
  strips, compositor); these reach widgets through ``ui.textual``.
- ``tests/native``, ``tests/terminal``: need a named outside requirement.
- ``tests/guards``: source checks that deleted mechanisms stay deleted.
"""
