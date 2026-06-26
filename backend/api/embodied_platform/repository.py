"""JSON-file repository for the embodied-only platform fallback backend."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, TypeVar
from uuid import uuid4

from .schema import SystemSettings


logger = logging.getLogger(__name__)


COLLECTIONS = [
    "datasets",
    "episodes",
    "imports",
    "annotation_tasks",
    "collection_profiles",
    "collection_runs",
    "collection_attempts",
    "training_jobs",
    "models",
    "simulation_jobs",
    "deployments",
    "learning_queue",
    "audit_events",
    "label_events",
    "telemetry_events",
]

_LOCKS: dict[Path, RLock] = {}
T = TypeVar("T")


def _lock_for(path: Path) -> RLock:
    # setdefault is atomic under the GIL: two threads racing on a first-seen path
    # can never observe two distinct RLock instances for the same key.
    return _LOCKS.setdefault(path.resolve(), RLock())


def data_root() -> Path:
    return Path(
        os.environ.get(
            "XINGJU_EMBODIED_PLATFORM_DATA_ROOT",
            Path(__file__).resolve().parents[2] / "data" / "embodied_platform",
        )
    )


def state_path() -> Path:
    return data_root() / "state.json"


def empty_state() -> dict[str, Any]:
    state: dict[str, Any] = {name: [] for name in COLLECTIONS}
    state["system_settings"] = SystemSettings().model_dump(mode="json")
    return state


def coerce_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Assemble a well-shaped state dict from raw stored values.

    Only recognized keys are carried over; any present-but-non-list collection
    is coerced to [] so a corrupt shape (e.g. {"datasets": 5}) cannot make
    every read endpoint 500 while iterating. Shared by JsonRepository and
    PgRepository so both backends degrade identically.
    """
    base = empty_state()
    for name in COLLECTIONS:
        value = raw.get(name)
        base[name] = value if isinstance(value, list) else []
    settings = raw.get("system_settings")
    if isinstance(settings, dict):
        base["system_settings"] = settings
    return base


def get_repository():
    """Select the state backend by env: DSN set -> Postgres, unset -> JSON file."""
    dsn = os.environ.get("XINGJU_EMBODIED_PLATFORM_DSN", "").strip()
    if dsn:
        from .pg_repository import PgRepository

        return PgRepository(dsn)
    return JsonRepository()


class JsonRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_path()
        self._lock = _lock_for(self.path)

    def read(self) -> dict[str, Any]:
        with self._lock:
            with self._file_lock(shared=True):
                return self._read_unlocked()

    def write(self, state: dict[str, Any]) -> None:
        with self._lock:
            with self._file_lock(shared=False):
                self._write_unlocked(state)

    def mutate(self, mutator: Callable[[dict[str, Any]], T]) -> T:
        with self._lock:
            with self._file_lock(shared=False):
                state = self._read_unlocked()
                result = mutator(state)
                self._write_unlocked(state)
                return result

    @contextmanager
    def _file_lock(self, *, shared: bool) -> Iterator[None]:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a")
        except OSError as exc:
            # On a read-only/unwritable data root the lock file cannot be
            # created. Writes (exclusive) must still fail loudly, but shared
            # reads degrade to a best-effort unlocked read so unauthenticated
            # GETs don't 500 on an ops misconfig. The in-process RLock still
            # serializes readers, and no writer can exist on a read-only root.
            if not shared:
                raise
            logger.warning("embodied platform lock unavailable, reading without lock: %s", exc)
            yield
            return
        with lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_state()
        try:
            with self.path.open() as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("embodied platform state file unreadable, using empty state: %s", exc)
            return empty_state()
        if not isinstance(state, dict):
            logger.warning(
                "embodied platform state file is not a JSON object (got %s), using empty state",
                type(state).__name__,
            )
            return empty_state()
        return coerce_state(state)

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{uuid4().hex}.tmp")
        try:
            with tmp.open("w") as f:
                # allow_nan=False so the on-disk state file is always RFC-8259
                # JSON (no bare NaN/Infinity tokens that other parsers reject).
                json.dump(state, f, indent=2, sort_keys=True, allow_nan=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
