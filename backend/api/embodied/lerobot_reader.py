"""Pure-read access to a LeRobotDataset v3.0 root — fps, camera keys, and
per-episode offsets. No ffmpeg, no HuggingFace, no network: just pyarrow + json.

Generalizes scripts/prep_embodied_demo.py::_episode_meta off the Hub so the
backend can serve any locally-recorded dataset root (XINGJU_EMBODIED_DATASET_ROOT).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq


@dataclass(frozen=True)
class EpisodeMeta:
    episode_index: int
    length: int
    fps: float
    task: str
    camera_keys: list[str]
    from_timestamp: float
    to_timestamp: float
    dataset_from_index: int
    dataset_to_index: int


def _info(dataset_root: Path) -> dict:
    return json.loads((dataset_root / "meta" / "info.json").read_text())


def _camera_keys(info: dict) -> list[str]:
    """All observation.images.* feature keys, in declaration order."""
    return [
        k for k, v in info.get("features", {}).items()
        if k.startswith("observation.images.") and v.get("dtype") == "video"
    ]


def _episodes_table_path(dataset_root: Path) -> Path:
    """Return the single meta/episodes parquet chunk (chunk-000/file-000.parquet).

    Only a single-chunk episodes parquet is supported today.
    Multi-chunk concat (for datasets with >chunks_size episodes) is a
    later-phase TODO; passing multiple chunks here would silently drop rows,
    so we fail loud instead.
    """
    matches = sorted((dataset_root / "meta" / "episodes").rglob("*.parquet"))
    if not matches:
        raise FileNotFoundError(
            f"no meta/episodes parquet under {dataset_root}"
        )
    if len(matches) > 1:
        raise NotImplementedError(
            f"multi-chunk episodes parquet not yet supported; found {len(matches)} chunks under {dataset_root}"
        )
    return matches[0]


def list_episodes(dataset_root: Path) -> list[EpisodeMeta]:
    info = _info(dataset_root)
    try:
        fps = float(info["fps"])
    except KeyError:
        raise KeyError(
            f"info.json missing required 'fps' key in {dataset_root}"
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"invalid fps value in info.json: {info['fps']!r} in {dataset_root}"
        ) from exc
    cam_keys = _camera_keys(info)
    if not cam_keys:
        raise ValueError(f"no observation.images.* camera in {dataset_root}")
    primary = cam_keys[0]

    cols = [
        "episode_index",
        "dataset_from_index",
        "dataset_to_index",
        "length",
        f"videos/{primary}/from_timestamp",
        f"videos/{primary}/to_timestamp",
        "tasks",
    ]
    table = pq.read_table(_episodes_table_path(dataset_root), columns=cols)

    ep_idx = table.column("episode_index").to_pylist()
    from_idx = table.column("dataset_from_index").to_pylist()
    to_idx = table.column("dataset_to_index").to_pylist()
    lengths = table.column("length").to_pylist()
    from_ts = table.column(f"videos/{primary}/from_timestamp").to_pylist()
    to_ts = table.column(f"videos/{primary}/to_timestamp").to_pylist()
    tasks = table.column("tasks").to_pylist()

    out: list[EpisodeMeta] = []
    for i in range(len(ep_idx)):
        task_list = tasks[i] or []
        out.append(
            EpisodeMeta(
                episode_index=int(ep_idx[i]),
                length=int(lengths[i]),
                fps=fps,
                task=task_list[0] if task_list else "",
                camera_keys=cam_keys,
                from_timestamp=float(from_ts[i]),
                to_timestamp=float(to_ts[i]),
                dataset_from_index=int(from_idx[i]),
                dataset_to_index=int(to_idx[i]),
            )
        )
    return out


def get_episode_meta(dataset_root: Path, episode_index: int) -> EpisodeMeta:
    for ep in list_episodes(dataset_root):
        if ep.episode_index == episode_index:
            return ep
    raise IndexError(
        f"episode {episode_index} not found in {dataset_root}"
    )
