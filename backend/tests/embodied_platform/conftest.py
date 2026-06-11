"""Pytest fixtures for embodied platform MVP tests.

The embodied platform API uses a JSON-file repository and never touches
Postgres. This repo has no parent ``backend/tests/conftest.py``, so there is
no session fixture to override; ``reset_schema`` below is a retained no-op
from the standalone-platform repo these tests were ported from (where it
shadowed a session-scoped Postgres schema reset). It is kept so the suite
stays drop-in compatible if these tests are ever vendored back.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def reset_schema():
    """No-op: nothing to reset — this repo has no Postgres and no parent fixture."""
    yield
