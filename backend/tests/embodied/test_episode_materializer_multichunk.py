"""Multi-chunk/file fail-loud guards in the episode materializer (issue #3).

These tests are deliberately ffmpeg-INDEPENDENT (no module-level skipif;
shutil.which and subprocess.run are faked) so they execute in *every* CI job,
not only where ffmpeg happens to be installed. "materializer" stays in the file
and test names so `pytest tests/embodied/ -k materializer` selects them.

Why this matters: the materializer slices observation.state with the GLOBAL
dataset_from/to_index, but read it from a hardcoded data/chunk-000/file-000
parquet (and a hardcoded video file-000.mp4). Once a recording overflows into a
second file, those global indices overrun file-000 and the materializer silently
sealed empty/truncated proprio behind the .complete sentinel — while the reader
(lerobot_reader._episodes_table_path) already fails loud on multi-chunk
meta/episodes. The fix mirrors that fail-loud contract on the data/video side.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import api.embodied.episode_materializer as mod
from api.embodied.episode_materializer import materialize
from api.embodied.lerobot_reader import get_episode_meta
from tests.embodied.fixtures import CAMERA_KEY, build_synthetic_lerobot_dataset


def _fake_tools(monkeypatch) -> None:
    """Pretend ffmpeg/ffprobe are installed and succeed without real encoding.

    Lets these tests drive materialize()'s control flow with no ffmpeg on PATH:
    the guards we assert on raise before any genuine subprocess work, and pre-fix
    the bug surfaces as a silently-sealed empty proprio rather than a tool error.
    Mirrors the fake_run pattern in test_episode_materializer.py.
    """
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":  # dst is always the final positional arg
            dst = Path(cmd[-1])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="8\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)


def test_materialize_multi_file_data_parquet_fails_loud(tmp_path, monkeypatch):
    """Data parquet spanning >1 file must raise, not slice past file-000's end."""
    _fake_tools(monkeypatch)
    # Episodes parquet stays single-chunk (reader passes); data spans 2 files.
    root = build_synthetic_lerobot_dataset(
        tmp_path / "ds", n_episodes=2, fps=10, data_files=2, with_video=False
    )
    # Episode 1's global slice [8:16] begins past file-000's rows — exactly the
    # case that silently returned empty proprio before the guard existed.
    ep1 = get_episode_meta(root, 1)
    assert ep1.dataset_from_index >= 8

    with pytest.raises(NotImplementedError, match="not yet supported"):
        materialize(root, 1, cache_root=tmp_path / "cache")

    # Fail-loud must not seal a (truncated) bundle behind the completion sentinel.
    assert not (tmp_path / "cache" / root.name / "ep1" / ".complete").exists()


def test_materialize_multi_file_video_fails_loud(tmp_path, monkeypatch):
    """Camera video spanning >1 mp4 must raise, not read a hardcoded file-000."""
    _fake_tools(monkeypatch)
    # Single-file data (reader + data guard pass), but the camera has two mp4s.
    root = build_synthetic_lerobot_dataset(
        tmp_path / "ds", n_episodes=2, fps=10, data_files=1, with_video=False
    )
    vid_dir = root / "videos" / CAMERA_KEY / "chunk-000"
    vid_dir.mkdir(parents=True, exist_ok=True)
    (vid_dir / "file-000.mp4").write_bytes(b"")
    (vid_dir / "file-001.mp4").write_bytes(b"")

    with pytest.raises(NotImplementedError, match="not yet supported"):
        materialize(root, 0, cache_root=tmp_path / "cache")

    assert not (tmp_path / "cache" / root.name / "ep0" / ".complete").exists()


def test_materialize_single_file_dataset_still_works(tmp_path, monkeypatch):
    """The guard must not regress the common single-chunk path: one data parquet
    and one video mp4 resolve and materialize to a sealed bundle as before."""
    _fake_tools(monkeypatch)
    root = build_synthetic_lerobot_dataset(
        tmp_path / "ds", n_episodes=2, fps=10, data_files=1, with_video=False
    )
    vid_dir = root / "videos" / CAMERA_KEY / "chunk-000"
    vid_dir.mkdir(parents=True, exist_ok=True)
    (vid_dir / "file-000.mp4").write_bytes(b"")

    bundle = materialize(root, 0, cache_root=tmp_path / "cache")
    assert (bundle.clip.parent / ".complete").exists()
