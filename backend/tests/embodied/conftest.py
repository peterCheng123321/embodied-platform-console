"""Pytest fixtures for embodied-AI labeler tests.

Embodied tests are pure Pydantic / FastAPI TestClient and do not need Postgres.
The parent conftest at backend/tests/conftest.py defines a session-scoped autouse
fixture `reset_schema` that connects to PG and blows away the schema. We override
it here with a no-op so embodied tests can run without a live database.

Pytest fixture resolution rule: when a fixture with the same name exists in both
parent and child conftest, the closer one wins — autouse still applied. The
parent conftest's module-level sys.path.insert(0, backend/) still runs because
the parent module is loaded; only the *fixture body* is replaced.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def reset_schema():
    """No-op override: embodied tests don't need a Postgres schema reset."""
    yield
