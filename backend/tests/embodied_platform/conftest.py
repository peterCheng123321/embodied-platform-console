"""Pytest fixtures for embodied platform MVP tests.

The embodied platform API uses a JSON-file repository and does not need the
project Postgres schema. Override the parent session fixture so these tests can
run when the local database is unavailable.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def reset_schema():
    """No-op override: embodied platform tests do not need Postgres."""
    yield
