"""Toolkit-neutral widget capability contracts, declared where any backend can inherit them.

These are the pure abstract contracts behind the Textual-side capability classes in
``widget_actions.py`` (``DismissibleControl``, ``Submits``, ``Selects``, ``OpensSelected``,
``Activates``). The Textual mixins carry Textual's ``DeclaredWidgetActions`` machinery
(``BindingsMap``, ``screen``, ``app._keymap``) which Qt cannot touch. The abstract methods
themselves — ``dismiss_control``, ``submit``, ``select``, ``open_selected``, ``activate`` —
are backend-neutral. Qt widgets inherit the contracts here and map their native dispatch
(``QDialog.reject``, button clicks, ``keyPressEvent``) onto the same method names, so a
cross-toolkit consumer can call ``widget.dismiss_control()`` without caring which backend
it drew.

Textual-side ``DismissibleControl`` etc. compose the matching contract into their MRO, so
``isinstance(widget, DismissibleControl)`` still answers yes on both backends.
"""

from __future__ import annotations

from abc import abstractmethod


class DismissibleContract:
    """A control that can be closed without the native screen result contract."""

    @abstractmethod
    def dismiss_control(self) -> None: ...


class SubmitsContract:
    """A control that can submit its current contents."""

    @abstractmethod
    def submit(self) -> None: ...


class SelectsContract:
    """A control whose selection can be committed from outside."""

    @abstractmethod
    def select(self) -> None: ...


class OpensSelectedContract:
    """A control that opens the row the user has cursored to."""

    @abstractmethod
    def open_selected(self) -> None: ...


class ActivatesContract:
    """A control whose primary effect is an own ``activate`` method."""

    @abstractmethod
    def activate(self) -> None: ...
