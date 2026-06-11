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

from fastapi import HTTPException

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
    return infos


def dataset_root_for(dataset_id: str) -> Path:
    if dataset_id == "demo":
        return DEMO_ROOT
    if dataset_id == "recorded":
        root = _recorded_root()
        if root is not None:
            return root
    raise HTTPException(status_code=404, detail=f"unknown dataset_id: {dataset_id}")
