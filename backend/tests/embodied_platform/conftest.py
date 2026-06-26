"""Pytest fixtures for embodied platform MVP tests.

Two storage modes:

- Default (no env): the API uses the JSON-file repository; tests isolate via
  per-test data roots, nothing to reset here.
- ``XINGJU_EMBODIED_PLATFORM_DSN`` set (the CI ``backend-postgres`` job): every
  route test shares one Postgres table, so ``reset_platform_state`` wipes the
  state back to ``empty_state()`` before each test through the same public
  repository surface the app uses. ``test_pg_repository.py`` manages its own
  throwaway schemas and is unaffected.
"""
from __future__ import annotations

import os

import pytest

_DSN = os.environ.get("XINGJU_EMBODIED_PLATFORM_DSN", "").strip()


@pytest.fixture(autouse=True)
def reset_platform_state():
    if _DSN:
        from api.embodied_platform.repository import empty_state, get_repository

        get_repository().write(empty_state())
    yield
