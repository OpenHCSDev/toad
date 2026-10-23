"""Authored outcomes for the real pytest harness regression, without starting Toad."""

import os
from pathlib import Path

import pytest

from support.roots import ATTEMPT


@pytest.fixture
def workspace():
    return Path(os.environ[ATTEMPT])


def test_app_failure(workspace):
    (workspace / "original-evidence.txt").write_text("Retain the actual failed attempt")
    assert False, "ACTUAL_APP_FAILURE_DIFFERS_FROM_CATALOGUE"


def test_unit_failure():
    assert False, "ACTUAL_UNIT_FAILURE_DIFFERS_FROM_CATALOGUE"


def test_app_pass(workspace):
    assert workspace.is_dir()


def test_unit_pass():
    pass
