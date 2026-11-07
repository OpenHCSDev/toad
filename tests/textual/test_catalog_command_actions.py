"""Every catalog command action binds to a real object.

`provider_login` binds an action and hands it to `ActionModal`, which reads only
`command_complete` and `description`; a base that declares something else abstract makes the
whole family uninstantiable and login dies with a TypeError (Toad log
WorkerFailed_2026-11-07T14_00_38, `provider_login`).
"""

import pytest

from toad.agent_schema import Command
from toad.catalog_actions import CatalogCommandAction, LoginAction, RunAction


def test_every_declared_action_binds():
    """A declared member must construct: `bind` passes its name straight to the constructor."""
    for name in CatalogCommandAction.names():
        action = CatalogCommandAction.bind(name, Command("Connect", "echo login"))
        assert isinstance(action, CatalogCommandAction), name
        assert action.name == name


def test_the_login_method_binds_its_own_action():
    """The call `provider_login` makes for a terminal auth method."""
    action = CatalogCommandAction.bind("login", Command("Login", "echo login"))
    assert isinstance(action, LoginAction)


def test_an_unknown_external_id_falls_back_to_the_script_action():
    """Hyphenated external IDs are not family members, so they run as a configured script."""
    action = CatalogCommandAction.bind("some-script", Command("Script", "echo hi"))
    assert type(action) is RunAction


def test_the_family_is_not_a_key_binding_action():
    """The base's obligation is the modal boundary, not a widget context nobody applies."""
    assert not hasattr(CatalogCommandAction, "apply"), (
        'a key-binding apply on this family is an obligation no member implements'
    )
