"""Postgres-backed state repository: one jsonb row per collection.

Same public surface as JsonRepository (``read() -> dict``, ``mutate(fn) -> Any``,
``write(state)``) so routes/event_routes are backend-agnostic. Writers are
serialized ACROSS HOSTS by ``SELECT … FOR UPDATE`` row locks; writes are
O(changed collections) because mutate() upserts only the collections the
mutator actually changed (version+1 per changed row).

Importing this module must not require a live database — connections are only
opened when a PgRepository is constructed (psycopg3 sync ConnectionPool, one
pool per DSN per process, shared by every instance like JsonRepository shares
one RLock per path).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from copy import deepcopy
from threading import Lock
from typing import Any, TypeVar

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .repository import COLLECTIONS, coerce_state

logger = logging.getLogger(__name__)

T = TypeVar("T")

# The recognized-key whitelist: exactly what coerce_state() carries over.
RECOGNIZED_KEYS = [*COLLECTIONS, "system_settings"]

# Arbitrary constant; serializes concurrent schema bootstrap (e.g. two replicas
# booting at once) so CREATE TABLE IF NOT EXISTS cannot race.
_BOOTSTRAP_LOCK_KEY = 914_201

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS embodied_platform_state (
    collection text PRIMARY KEY,
    doc        jsonb NOT NULL DEFAULT '[]'::jsonb,
    version    bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""

# FOR UPDATE cannot lock rows that do not exist, so every recognized collection
# is seeded with a default row: mutate()'s SELECT … FOR UPDATE then always
# locks the COMPLETE row set and writers fully serialize. '[]' is a safe seed
# for system_settings too — coerce_state() only accepts a dict there, so a
# non-dict seed means "defaults at read time", exactly like a missing JSON key.
_SEED_SQL = """
INSERT INTO embodied_platform_state (collection)
SELECT unnest(%s::text[])
ON CONFLICT (collection) DO NOTHING
"""

_UPSERT_SQL = """
INSERT INTO embodied_platform_state (collection, doc, version, updated_at)
VALUES (%s, %s, 1, now())
ON CONFLICT (collection) DO UPDATE
SET doc = EXCLUDED.doc,
    version = embodied_platform_state.version + 1,
    updated_at = now()
"""

_POOLS: dict[str, ConnectionPool] = {}
_POOLS_LOCK = Lock()


def _strict_dumps(value: Any) -> str:
    # allow_nan=False parity with JsonRepository._write_unlocked: stored docs
    # are always RFC-8259 JSON (a NaN raises ValueError and the transaction
    # rolls back instead of persisting a non-spec token).
    return json.dumps(value, allow_nan=False)


def _ensure_schema(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_BOOTSTRAP_LOCK_KEY,))
            conn.execute(_SCHEMA_SQL)
            conn.execute(_SEED_SQL, (RECOGNIZED_KEYS,))


def _pool_for(dsn: str) -> ConnectionPool:
    with _POOLS_LOCK:
        pool = _POOLS.get(dsn)
        if pool is None:
            pool = ConnectionPool(dsn, min_size=1, max_size=10, open=False)
            try:
                pool.open(wait=True, timeout=30.0)
                _ensure_schema(pool)
            except BaseException:
                pool.close()
                raise
            _POOLS[dsn] = pool
        return pool


def close_pool(dsn: str) -> None:
    """Close and forget the cached pool for *dsn* (test-teardown helper)."""
    with _POOLS_LOCK:
        pool = _POOLS.pop(dsn, None)
    if pool is not None:
        pool.close()


class PgRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        # First construction for a DSN opens the pool and ensures the schema;
        # later constructions (one per request via the factory) reuse it.
        self._pool = _pool_for(dsn)

    def read(self) -> dict[str, Any]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT collection, doc FROM embodied_platform_state"
            ).fetchall()
        return coerce_state(dict(rows))

    def write(self, state: dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            with conn.transaction():
                # Lock the full row set first so a whole-state write serializes
                # against concurrent mutate() calls without deadlocking them.
                conn.execute("SELECT collection FROM embodied_platform_state FOR UPDATE")
                for name in RECOGNIZED_KEYS:
                    self._upsert(conn, name, state.get(name))

    def mutate(self, mutator: Callable[[dict[str, Any]], T]) -> T:
        with self._pool.connection() as conn:
            with conn.transaction():
                # Re-seed any missing rows (e.g. after an external TRUNCATE) so
                # the FOR UPDATE below always locks the complete row set.
                conn.execute(_SEED_SQL, (RECOGNIZED_KEYS,))
                rows = conn.execute(
                    "SELECT collection, doc FROM embodied_platform_state FOR UPDATE"
                ).fetchall()
                state = coerce_state(dict(rows))
                before = deepcopy(state)
                # A mutator exception propagates out of conn.transaction(),
                # which rolls back — nothing is committed.
                result = mutator(state)
                for name in RECOGNIZED_KEYS:
                    if state.get(name) != before.get(name):
                        self._upsert(conn, name, state.get(name))
            return result

    @staticmethod
    def _upsert(conn: Any, name: str, value: Any) -> None:
        conn.execute(_UPSERT_SQL, (name, Jsonb(value, dumps=_strict_dumps)))
