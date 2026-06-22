"""Synthetic LeRobotDataset v3.0 fixture builder for embodied tests.

build_synthetic_lerobot_dataset writes a minimal valid v3.0 dataset to a tmp
dir: meta/info.json, meta/episodes parquet (per-episode offsets), data parquet
(observation.state rows), and one tiny real .mp4 per camera. No network, no HF.
The reader (api.embodied.lerobot_reader) and the Phase 2 materializer are tested
against the output of this builder.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

CAMERA_KEY = "observation.images.exterior_image_1_left"
STATE_DIM = 7
TASK_TEXT = "pick up the cube"

_EP_LEN = 8  # frames per episode (kept tiny so the mp4 is small/fast)


def build_synthetic_lerobot_dataset(
    tmp_path: Path,
    *,
    n_episodes: int = 2,
    fps: int = 10,
    start_index: int = 0,
    with_video: bool = True,
    data_files: int = 1,
) -> Path:
    """Write a minimal valid LeRobotDataset v3.0 to tmp_path/dataset and return it.

    Layout (mirrors lerobot/droid_100):
      meta/info.json
      meta/episodes/chunk-000/file-000.parquet   (one row per episode)
      data/chunk-000/file-000.parquet            (observation.state rows)
      videos/<CAMERA_KEY>/chunk-000/file-000.mp4  (tiny real mp4; skipped if with_video=False)

    Each episode is _EP_LEN frames. Per-episode video timestamps run
    [ep_offset*EP_SECONDS, (ep_offset+1)*EP_SECONDS). dataset_from/to_index
    slice the concatenated data parquet (always 0-based regardless of start_index).

    start_index: first value written to the episode_index column (default 0).
      Use a non-zero start_index in tests to distinguish value-lookup from
      positional indexing.
    with_video: when False, skip ffmpeg mp4 generation. Set False for pure
      reader tests that never touch mp4 files.
    data_files: number of data parquet files to split the frame rows across
      (data/chunk-000/file-{i:03d}.parquet). Defaults to 1 (single file). Use >1
      to build a dataset whose episodes parquet is single-chunk (reader passes)
      but whose data parquet spans multiple files, so a global
      dataset_from/to_index can fall outside file-000 — the case the
      materializer's multi-chunk guard must catch (issue #3).
    """
    root = tmp_path / "dataset"

    # --- meta/info.json (real v3.0 shape, single camera + observation.state) ---
    info = {
        "codebase_version": "v3.0",
        "robot_type": "unknown",
        "total_episodes": n_episodes,
        "total_frames": _EP_LEN * n_episodes,
        "fps": fps,
        "chunks_size": 1000,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {
            CAMERA_KEY: {
                "dtype": "video",
                "shape": [180, 320, 3],
                "names": ["height", "width", "channel"],
                "video_info": {
                    "video.fps": float(fps),
                    "video.codec": "h264",
                    "video.pix_fmt": "yuv420p",
                    "video.is_depth_map": False,
                    "has_audio": False,
                },
            },
            "observation.state": {
                "dtype": "float32",
                "shape": [STATE_DIM],
                "names": {"motors": [f"motor_{i}" for i in range(STATE_DIM)]},
                "fps": float(fps),
            },
        },
    }
    info_path = root / "meta" / "info.json"
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info, indent=2))

    # --- meta/episodes parquet (per-episode offsets) ---
    # episode_index is offset by start_index; data indices are always 0-based.
    ep_seconds = _EP_LEN / fps
    episode_index, from_idx, to_idx, length, from_ts, to_ts, tasks = [], [], [], [], [], [], []
    for ep in range(n_episodes):
        episode_index.append(start_index + ep)
        from_idx.append(ep * _EP_LEN)
        to_idx.append((ep + 1) * _EP_LEN)
        length.append(_EP_LEN)
        from_ts.append(ep * ep_seconds)
        to_ts.append((ep + 1) * ep_seconds)
        tasks.append([TASK_TEXT])  # list<string> — reader does tasks[i][0]

    eps_table = pa.table(
        {
            "episode_index": pa.array(episode_index, type=pa.int64()),
            "dataset_from_index": pa.array(from_idx, type=pa.int64()),
            "dataset_to_index": pa.array(to_idx, type=pa.int64()),
            "length": pa.array(length, type=pa.int64()),
            f"videos/{CAMERA_KEY}/from_timestamp": pa.array(from_ts, type=pa.float64()),
            f"videos/{CAMERA_KEY}/to_timestamp": pa.array(to_ts, type=pa.float64()),
            "tasks": pa.array(tasks, type=pa.list_(pa.string())),
        }
    )
    eps_path = root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    eps_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(eps_table, eps_path)

    # --- data parquet(s) (observation.state, one list[float] per frame) ---
    n_frames = _EP_LEN * n_episodes
    state_rows = [[float(i + j * 0.1) for j in range(STATE_DIM)] for i in range(n_frames)]
    # Split the frame rows across `data_files` parquet files. Episodes parquet
    # stays single-chunk, so the reader still passes while data spans >1 file —
    # the exact split that lets a global dataset_from/to_index overrun file-000
    # (exercises the materializer's multi-chunk fail-loud guard, issue #3).
    per_file = -(-n_frames // data_files)  # ceil division, no import
    for fi in range(data_files):
        chunk_rows = state_rows[fi * per_file:(fi + 1) * per_file]
        if not chunk_rows:
            continue
        data_table = pa.table(
            {"observation.state": pa.array(chunk_rows, type=pa.list_(pa.float32()))}
        )
        data_path = root / "data" / "chunk-000" / f"file-{fi:03d}.parquet"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(data_table, data_path)

    # --- one tiny real mp4 (ffmpeg testsrc) for the Phase 2 materializer ---
    if with_video:
        mp4_path = root / "videos" / CAMERA_KEY / "chunk-000" / "file-000.mp4"
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        total_seconds = ep_seconds * n_episodes
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"testsrc=size=320x180:rate={fps}:duration={total_seconds:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                str(mp4_path),
            ],
            check=True,
            capture_output=True,
        )

    return root


def _self_test_fixture_loads(tmp_path: Path) -> None:
    """Self-test (invoked by test_fixtures.py): the written dataset is valid."""
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=2, fps=10)

    info = json.loads((root / "meta" / "info.json").read_text())
    assert info["codebase_version"] == "v3.0"
    assert info["fps"] == 10
    cam_keys = [k for k in info["features"] if k.startswith("observation.images.")]
    assert cam_keys == ["observation.images.exterior_image_1_left"]
    assert info["features"]["observation.state"]["dtype"] == "float32"

    eps_files = sorted((root / "meta" / "episodes").rglob("*.parquet"))
    assert len(eps_files) == 1
    t = pq.read_table(eps_files[0])
    assert t.num_rows == 2
    assert t.column("episode_index").to_pylist() == [0, 1]
    # The tasks column MUST be list<string>, not scalar string: the reader does
    # tasks[i][0]. A scalar would pass a naive write and break the reader.
    assert pa.types.is_list(t.schema.field("tasks").type)
    assert t.column("tasks").to_pylist()[0] == ["pick up the cube"]

    data_files = sorted((root / "data").rglob("*.parquet"))
    assert len(data_files) == 1
    d = pq.read_table(data_files[0])
    # observation.state rows total = sum of episode lengths.
    assert d.num_rows == t.column("length").to_pylist()[0] + t.column("length").to_pylist()[1]

    cam = cam_keys[0]
    mp4s = sorted((root / "videos" / cam).rglob("*.mp4"))
    assert len(mp4s) == 1 and mp4s[0].stat().st_size > 0
