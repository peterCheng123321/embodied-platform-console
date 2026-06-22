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


@pytest.fixture(autouse=True)
def _embodied_auth_secret(monkeypatch):
    """Configure the principal-signing secret for every embodied test.

    Segment routes now require a valid platform principal signature (issue #2),
    which `sign_principal`/`_verify_principal_signature` derive from this env
    var. Setting it here (autouse) lets test helpers mint signatures the routes
    accept; route-free tests (reader/materializer/fixtures) are unaffected.
    """
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "test-embodied-principal-secret")
