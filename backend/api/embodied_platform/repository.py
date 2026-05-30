"""JSON-file repository for the embodied-only platform fallback backend."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, TypeVar
from uuid import uuid4

from .schema import SystemSettings


COLLECTIONS = [
    "datasets",
    "episodes",
    "imports",
    "annotation_tasks",
    "training_jobs",
    "models",
    "simulation_jobs",
    "deployments",
    "learning_queue",
    "audit_events",
]

_LOCKS: dict[Path, RLock] = {}
T = TypeVar("T")


def _lock_for(path: Path) -> RLock:
    resolved = path.resolve()
    if resolved not in _LOCKS:
        _LOCKS[resolved] = RLock()
    return _LOCKS[resolved]


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with lock_path.open("a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_state()
        with self.path.open() as f:
            state = json.load(f)
        base = empty_state()
        base.update(state)
        for name in COLLECTIONS:
            base.setdefault(name, [])
        base.setdefault("system_settings", SystemSettings().model_dump(mode="json"))
        return base

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{uuid4().hex}.tmp")
        try:
            with tmp.open("w") as f:
                json.dump(state, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
