"""Shared pytest fixtures."""

import pytest

from data.create_db import build_database


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """A fresh sample database in a temp dir, shared by all tests in the session."""
    return build_database(tmp_path_factory.mktemp("db") / "test.db")
