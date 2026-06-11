"""Tests for episode_materializer: ffmpeg clip + parquet proprio + sprite + meta."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.embodied.fixtures import build_synthetic_lerobot_dataset
from api.embodied.episode_materializer import BundlePaths, materialize


def _ffprobe_frame_count(mp4: Path) -> int:
    res = subprocess.run(
        ["ffprobe", "-v", "0", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)],
        check=True, capture_output=True, text=True,
    )
    return int(res.stdout.strip())


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture
def dataset_root(tmp_path) -> Path:
    return build_synthetic_lerobot_dataset(tmp_path / "ds", n_episodes=2, fps=10)


def test_materialize_writes_four_bundle_files(dataset_root, tmp_path):
    cache = tmp_path / "cache"
    bundle = materialize(dataset_root, 0, cache_root=cache)
    assert isinstance(bundle, BundlePaths)
    for p in (bundle.clip, bundle.proprio, bundle.sprite, bundle.meta):
        assert p.exists(), f"missing {p}"
    # Output dir convention: cache_root/<dataset_id>/ep<index>/
    assert bundle.clip.parent == cache / dataset_root.name / "ep0"
    assert bundle.clip.name == "clip.mp4"
    assert bundle.proprio.name == "proprio.json"
    assert bundle.sprite.name == "sprite.png"
    assert bundle.meta.name == "episode_meta.json"


def test_proprio_length_equals_episode_length(dataset_root, tmp_path):
    from api.embodied.lerobot_reader import get_episode_meta
    bundle = materialize(dataset_root, 1, cache_root=tmp_path / "cache")
    proprio = json.loads(bundle.proprio.read_text())
    ep_len = get_episode_meta(dataset_root, 1).length
    assert len(proprio) == ep_len
    # default single channel -> flat list[float]
    assert all(isinstance(v, float) for v in proprio)


def test_episode_meta_total_frames_matches_ffprobe(dataset_root, tmp_path):
    bundle = materialize(dataset_root, 0, cache_root=tmp_path / "cache")
    meta = json.loads(bundle.meta.read_text())
    assert meta["total_frames"] == _ffprobe_frame_count(bundle.clip)
    assert meta["episode_index"] == 0
    assert meta["dataset_from_index"] == 0  # ep0 starts at row 0
    assert isinstance(meta["fps"], (int, float)) and meta["fps"] > 0
    assert meta["camera"]  # non-empty primary camera key
    assert "task" in meta


def test_default_camera_and_channel_resolution(dataset_root, tmp_path):
    """camera_key=None, proprio_channels=None resolve from Phase-1 meta / info.json."""
    from api.embodied.lerobot_reader import get_episode_meta
    meta_obj = get_episode_meta(dataset_root, 0)
    bundle = materialize(dataset_root, 0, cache_root=tmp_path / "cache")
    meta = json.loads(bundle.meta.read_text())
    # primary camera = first camera key from Phase-1 reader
    assert meta["camera"] == meta_obj.camera_keys[0]
    # default channel = last observation.state dim, read from info.json shape
    info = json.loads((dataset_root / "meta" / "info.json").read_text())
    state_dim = info["features"]["observation.state"]["shape"][0]
    proprio = json.loads(bundle.proprio.read_text())
    assert len(proprio) == meta_obj.length  # one value per frame, single channel
    assert state_dim >= 1


def test_multi_channel_proprio_is_list_of_lists(dataset_root, tmp_path):
    bundle = materialize(dataset_root, 0, cache_root=tmp_path / "cache",
                         proprio_channels=[0, 1])
    proprio = json.loads(bundle.proprio.read_text())
    from api.embodied.lerobot_reader import get_episode_meta
    assert len(proprio) == get_episode_meta(dataset_root, 0).length
    assert all(isinstance(row, list) and len(row) == 2 for row in proprio)


def test_idempotent_second_call_is_noop(dataset_root, tmp_path):
    cache = tmp_path / "cache"
    first = materialize(dataset_root, 0, cache_root=cache)
    mtimes = {p: p.stat().st_mtime_ns
              for p in (first.clip, first.proprio, first.sprite, first.meta)}
    second = materialize(dataset_root, 0, cache_root=cache)
    assert second == first
    for p, m in mtimes.items():
        assert p.stat().st_mtime_ns == m, f"{p} was rewritten on idempotent call"


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_missing_tool_raises_runtimeerror(dataset_root, tmp_path, monkeypatch, missing):
    import api.embodied.episode_materializer as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: None if name == missing else f"/usr/bin/{name}")
    with pytest.raises(RuntimeError, match=missing):
        materialize(dataset_root, 0, cache_root=tmp_path / "cache")


def test_incomplete_bundle_is_rebuilt(dataset_root, tmp_path):
    """A crashed run (no .complete) causes the next call to rebuild, not return stale data."""
    cache = tmp_path / "cache"
    first = materialize(dataset_root, 0, cache_root=cache)
    sentinel = first.clip.parent / ".complete"
    assert sentinel.exists(), ".complete not written after successful materialize"
    sentinel.unlink()  # simulate a crash after writing files but before sentinel
    clip_mtime_before = first.clip.stat().st_mtime_ns
    second = materialize(dataset_root, 0, cache_root=cache)
    assert second.clip.stat().st_mtime_ns != clip_mtime_before, "clip was not rebuilt after .complete removal"
    assert sentinel.exists(), ".complete not re-created after rebuild"
