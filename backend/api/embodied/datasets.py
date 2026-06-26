"""Embodied dataset registry.

Resolves a stable ``dataset_id`` (used in URLs and persisted with each
annotation row) to an on-disk dataset root, and lists the datasets the
labeler may open.

- ``"demo"`` is always present and maps to the built-in trimmed DROID clip
  shipped under ``assets/embodied/`` (kind ``"demo"``, single episode).
- ``"recorded"`` appears iff ``XINGJU_EMBODIED_DATASET_ROOT`` points at a
  recorded LeRobotDataset root (kind ``"lerobot"``); its episode count comes
  from the per-episode meta parquet via the Phase-1 reader.

Unknown ids raise ``HTTPException(404)`` so route handlers can let it bubble.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from api.embodied_platform.repository import get_repository as get_platform_repository

from .lerobot_reader import list_episodes


logger = logging.getLogger(__name__)


# Built-in demo asset dir, resolved relative to this file:
# backend/api/embodied/datasets.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = _REPO_ROOT / "apps" / "embodied-labeler" / "assets" / "embodied"


@dataclass(frozen=True)
class DatasetInfo:
    id: str
    label: str
    kind: str  # "demo" | "lerobot"
    episode_count: int


def _recorded_root() -> Path | None:
    raw = os.environ.get("XINGJU_EMBODIED_DATASET_ROOT")
    if not raw:
        return None
    return Path(raw)


def _local_dataset_root(storage_uri: str | None) -> Path | None:
    raw = (storage_uri or "").strip()
    if not raw:
        return None
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.netloc not in {"", "localhost"}:
            return None
        path = unquote(parsed.path)
        return Path(path) if path else None
    if "://" in raw:
        return None
    return Path(raw)


def list_datasets() -> list[DatasetInfo]:
    infos = [
        DatasetInfo(id="demo", label="Demo (DROID clip)", kind="demo", episode_count=1),
    ]
    root = _recorded_root()
    if root is not None:
        try:
            infos.append(
                DatasetInfo(
                    id="recorded",
                    label="Recorded dataset",
                    kind="lerobot",
                    episode_count=len(list_episodes(root)),
                )
            )
        except FileNotFoundError as exc:
            # A stale/nonexistent XINGJU_EMBODIED_DATASET_ROOT must not 500
            # the registry and hide the always-available demo dataset: skip
            # the recorded entry with a warning instead. dataset_root_for
            # still resolves "recorded", so direct episode fetches surface
            # their own errors.
            logger.warning("skipping recorded dataset (root unreadable): %s", exc)
    for item in _platform_lerobot_datasets():
        if item.id not in {info.id for info in infos}:
            infos.append(item)
    return infos


def dataset_root_for(dataset_id: str) -> Path:
    if dataset_id == "demo":
        return DEMO_ROOT
    if dataset_id == "recorded":
        root = _recorded_root()
        if root is not None:
            return root
    platform_root = _platform_dataset_root_for(dataset_id)
    if platform_root is not None:
        return platform_root
    raise HTTPException(status_code=404, detail=f"unknown dataset_id: {dataset_id}")


def _platform_lerobot_datasets() -> list[DatasetInfo]:
    try:
        state = get_platform_repository().read()
    except Exception as exc:
        logger.warning("platform dataset registry unavailable: %s", exc)
        return []
    infos: list[DatasetInfo] = []
    for dataset in state.get("datasets", []):
        if not isinstance(dataset, dict):
            continue
        root = _local_dataset_root(str(dataset.get("storage_uri") or ""))
        if root is None:
            continue
        try:
            episodes = list_episodes(root)
        except (FileNotFoundError, IndexError, NotImplementedError, OSError, ValueError) as exc:
            logger.warning("skipping platform dataset %s: %s", dataset.get("id"), exc)
            continue
        dataset_id = str(dataset.get("id") or dataset.get("name") or "")
        if not dataset_id:
            continue
        infos.append(
            DatasetInfo(
                id=dataset_id,
                label=str(dataset.get("name") or dataset_id),
                kind="lerobot",
                episode_count=len(episodes),
            )
        )
    return infos


def _platform_dataset_root_for(dataset_id: str) -> Path | None:
    try:
        state = get_platform_repository().read()
    except Exception as exc:
        logger.warning("platform dataset registry unavailable: %s", exc)
        return None
    for dataset in state.get("datasets", []):
        if not isinstance(dataset, dict):
            continue
        if dataset_id not in {str(dataset.get("id") or ""), str(dataset.get("name") or "")}:
            continue
        return _local_dataset_root(str(dataset.get("storage_uri") or ""))
    return None
