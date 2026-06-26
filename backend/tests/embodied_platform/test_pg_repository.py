"""PgRepository tests — the full shared contract plus Postgres-specific pins.

These run for real only against a live Postgres (CI's backend-postgres job,
postgres:16 service container). Locally they SKIP loudly unless a disposable
DSN is provided. Each test gets a throwaway schema (search_path via conninfo
options) that is dropped afterwards, so the target database is never polluted.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from .repository_contract import ALL_CONTRACTS

DSN = os.environ.get("XINGJU_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="XINGJU_TEST_PG_DSN unset — Postgres repository tests run in CI (backend-postgres job); "
    "set a disposable DSN to run locally. THIS SKIP IS EXPECTED LOCALLY.",
)


@pytest.fixture()
def pg_make_repo():
    """Yield a zero-arg PgRepository factory over a throwaway per-test schema."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from api.embodied_platform import pg_repository

    schema = f"pgrepo_test_{uuid4().hex[:12]}"
    test_dsn = make_conninfo(DSN, options=f"-csearch_path={schema}")
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield lambda: pg_repository.PgRepository(test_dsn)
    finally:
        pg_repository.close_pool(test_dsn)
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("contract", ALL_CONTRACTS, ids=lambda fn: fn.__name__)
def test_pg_repository_satisfies_shared_contract(contract, pg_make_repo):
    """Every backend-agnostic contract function (already proven against
    JsonRepository in test_repository_robustness.py) must hold for PgRepository."""
    contract(pg_make_repo)


def test_interleaved_mutates_across_instances_never_lose_updates(pg_make_repo):
    """Two PgRepository instances on the same DSN stand in for two hosts:
    interleaved concurrent mutates must never lose an update (SELECT … FOR
    UPDATE row locks serialize writers). Ported from the JSON parallel-writes
    test: 40 appends from 8 threads across both instances all survive."""
    from concurrent.futures import ThreadPoolExecutor

    repo_a, repo_b = pg_make_repo(), pg_make_repo()

    def write_event(index: int) -> int:
        repo = repo_a if index % 2 == 0 else repo_b

        def _mutate(state: dict) -> int:
            state["audit_events"].append(
                {
                    "id": f"audit-{index}",
                    "action": "stress.write",
                    "resource": f"resource-{index}",
                    "detail": "parallel writer",
                    "actor": "pytest",
                    "role": "admin",
                    "created_at": "2026-05-30T00:00:00+00:00",
                }
            )
            return index

        return repo.mutate(_mutate)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sorted(pool.map(write_event, range(40))) == list(range(40))

    assert len(pg_make_repo().read()["audit_events"]) == 40


def test_version_increments_only_for_changed_collections(pg_make_repo):
    """mutate() upserts ONLY collections the mutator actually changed: their
    version bumps by one per write; untouched collections stay at version 0."""
    import psycopg

    repo = pg_make_repo()

    def add_dataset(state):
        state["datasets"].append({"id": "ds_v1", "name": "versioned"})

    def add_model(state):
        state["models"].append({"id": "m_v1", "name": "versioned"})

    repo.mutate(add_dataset)
    repo.mutate(add_model)

    with psycopg.connect(repo.dsn) as conn:
        versions = dict(
            conn.execute("SELECT collection, version FROM embodied_platform_state").fetchall()
        )
    assert versions["datasets"] == 1
    assert versions["models"] == 1
    untouched = {name: v for name, v in versions.items() if name not in ("datasets", "models")}
    assert untouched and all(v == 0 for v in untouched.values()), untouched


def test_corrupt_doc_coerces_on_read_like_json_repository(pg_make_repo):
    """A manually corrupted doc (non-list jsonb) must coerce to [] on read —
    the same '{"datasets":5}' degrade JsonRepository pins — never a 500-shaped
    crash while iterating."""
    import psycopg

    repo = pg_make_repo()
    repo.mutate(lambda state: state["datasets"].append({"id": "ds_x", "name": "x"}))

    with psycopg.connect(repo.dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE embodied_platform_state SET doc = %s::jsonb WHERE collection = 'datasets'",
            ('"not a list"',),
        )

    state = pg_make_repo().read()
    assert state["datasets"] == []
    assert state["models"] == []  # the rest of the state still assembles


def test_mutator_exception_rolls_back_without_commit(pg_make_repo):
    """mutate() must re-raise the mutator's exception WITHOUT committing: the
    transaction rolls back, so partial in-memory edits never persist (parity
    with JsonRepository, which only writes after the mutator returns)."""

    def explode(state):
        state["datasets"].append({"id": "ds_doomed", "name": "doomed"})
        raise RuntimeError("mutator failed mid-flight")

    repo = pg_make_repo()
    with pytest.raises(RuntimeError, match="mid-flight"):
        repo.mutate(explode)

    assert pg_make_repo().read()["datasets"] == []
