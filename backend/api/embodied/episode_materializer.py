"""Materialize one LeRobot episode into a self-contained bundle for the labeler.

Given a recorded LeRobotDataset root and an episode index, produce:
    cache_root/<dataset_id>/ep<index>/clip.mp4          full-episode H.264 clip
                                       /proprio.json      per-frame proprio (selected channels)
                                       /sprite.png        thumbnail filmstrip
                                       /episode_meta.json authoritative fps/frames/camera/task

Reuses the exact ffmpeg/ffprobe invocations from scripts/prep_embodied_demo.py,
adapted for variable-length episodes (no TRIM_SECONDS cap, no proprio max_frames
cap) and library semantics (raises instead of sys.exit). Episode timing/offsets/
camera come from the Phase-1 reader (get_episode_meta); this module never re-reads
meta/episodes/*.parquet. Its only pyarrow use is slicing observation.state.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .lerobot_reader import get_episode_meta

# Sprite tiling — one thumb per 0.5s, matches prep_embodied_demo.py.
SPRITE_FPS = 2
SPRITE_W, SPRITE_H = 128, 72

# Hard wall-clock ceilings for the external tools. Sync route handlers run in
# Starlette's bounded threadpool while holding the per-episode materialize
# lock — a hung ffmpeg/ffprobe (corrupt mp4, dead NFS mount) would otherwise
# pin that thread and lock forever. ffprobe only reads stream metadata (30s is
# generous); ffmpeg re-encodes a full episode clip (120s covers long episodes
# on slow disks while still bounding the worst case).
FFPROBE_TIMEOUT_SECONDS = 30
FFMPEG_TIMEOUT_SECONDS = 120


class MaterializeTimeoutError(RuntimeError):
    """An ffmpeg/ffprobe invocation exceeded its wall-clock timeout.

    A RuntimeError subclass so existing handlers of the module's documented
    error type keep working, while routes can map timeouts to 503."""


@dataclass(frozen=True)
class BundlePaths:
    clip: Path
    proprio: Path
    sprite: Path
    meta: Path


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise RuntimeError(
            f"{tool} not on PATH — install ffmpeg (brew install ffmpeg) to materialize episodes"
        )


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing stderr; on failure re-raise as RuntimeError.

    Every invocation carries a wall-clock timeout: a hung tool raises
    MaterializeTimeoutError instead of pinning the worker thread (and the
    caller's per-episode lock) forever.
    """
    try:
        return subprocess.run(
            cmd, check=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise MaterializeTimeoutError(
            f"{cmd[0]} timed out after {timeout:.0f}s while materializing the episode"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"{cmd[0]} failed (exit {e.returncode}): {e.stderr.strip()}"
        ) from e


def _ffprobe_frame_count(mp4: Path) -> int:
    res = _run([
        "ffprobe", "-v", "0", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(mp4),
    ], timeout=FFPROBE_TIMEOUT_SECONDS)
    raw = res.stdout.strip()
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"ffprobe returned unexpected frame count: {raw!r}") from None


def _default_state_dim(dataset_root: Path) -> int:
    """Last observation.state dim index, from info.json shape (Phase-1 seam)."""
    info = json.loads((dataset_root / "meta" / "info.json").read_text())
    shape = info["features"]["observation.state"]["shape"]
    return int(shape[0]) - 1


def _trim_clip(src_mp4: Path, dst: Path, from_ts: float, duration: float) -> None:
    """Seek to episode start, copy full episode (no TRIM_SECONDS cap), re-encode.

    Exact ffmpeg flags from prep_embodied_demo.py::trim_video: -ss BEFORE -i
    (fast input seek), libx264 / crf 23 / preset slow, audio stripped.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-y", "-ss", f"{from_ts:.3f}", "-i", str(src_mp4),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-crf", "23", "-preset", "slow", "-an", str(dst),
    ], timeout=FFMPEG_TIMEOUT_SECONDS)


def _generate_sprite(clip_mp4: Path, dst_png: Path, duration: float) -> None:
    """One frame per 0.5s tiled into a horizontal filmstrip.

    Tile count is computed from the actual episode duration — prep hardcodes
    TRIM_SECONDS*SPRITE_FPS (=30), which mis-tiles variable-length episodes.
    """
    n_tiles = max(1, math.ceil(duration * SPRITE_FPS))
    _run([
        "ffmpeg", "-y", "-i", str(clip_mp4),
        "-vf", f"fps={SPRITE_FPS},scale={SPRITE_W}:{SPRITE_H},tile={n_tiles}x1",
        "-frames:v", "1", str(dst_png),
    ], timeout=FFMPEG_TIMEOUT_SECONDS)


def _single_media_file(directory: Path, pattern: str, label: str) -> Path:
    """Resolve the one chunk/file under ``directory`` matching ``pattern``.

    Mirrors lerobot_reader._episodes_table_path's fail-loud contract: multi-chunk
    concatenation is a later-phase TODO, so >1 match raises NotImplementedError
    rather than silently reading file-000 and slicing it with the GLOBAL row
    indices that overrun its end. The meta side already fails loud; the data and
    video sides must match it instead of sealing empty/truncated proprio behind
    the .complete sentinel (issue #3).
    """
    matches = sorted(directory.rglob(pattern))
    if not matches:
        raise FileNotFoundError(f"no {label} under {directory}")
    if len(matches) > 1:
        raise NotImplementedError(
            f"multi-chunk {label} not yet supported; "
            f"found {len(matches)} files under {directory}"
        )
    return matches[0]


def _extract_proprio(
    pq_path: Path,
    from_index: int,
    to_index: int,
    channels: list[int],
) -> list:
    """Slice observation.state rows [from_index:to_index] from the data parquet.

    `pq_path` is the single data chunk/file resolved by `_single_media_file`
    (multi-file datasets fail loud upstream, so the global from/to indices here
    always address this one file). No max_frames cap (prep caps to TRIM_SECONDS);
    the full slice survives so the proprio length equals the episode length.
    Single channel -> flat list[float]; multiple channels -> list[list[float]],
    one inner list per frame.
    """
    import pyarrow.parquet as pq_lib  # Phase-1 dependency

    t = pq_lib.read_table(pq_path, columns=["observation.state"])
    state = t["observation.state"].to_pylist()  # list[list[float]]
    sliced = state[from_index:to_index]
    if len(channels) == 1:
        c = channels[0]
        return [float(row[c]) if row else 0.0 for row in sliced]
    return [[float(row[c]) for c in channels] if row else [0.0] * len(channels)
            for row in sliced]


def materialize(
    dataset_root: Path,
    episode_index: int,
    *,
    cache_root: Path,
    camera_key: str | None = None,
    proprio_channels: list[int] | None = None,
) -> BundlePaths:
    """Materialize one episode into cache_root/<dataset_id>/ep<index>/.

    Idempotent: if the `.complete` sentinel exists inside the output dir,
    return immediately without invoking ffmpeg. Camera/channel defaults resolve
    from the Phase-1 reader and info.json. Raises RuntimeError if
    ffmpeg/ffprobe is missing or fails.
    """
    dataset_root = Path(dataset_root)
    dataset_id = dataset_root.name
    out_dir = Path(cache_root) / dataset_id / f"ep{episode_index}"
    bundle = BundlePaths(
        clip=out_dir / "clip.mp4",
        proprio=out_dir / "proprio.json",
        sprite=out_dir / "sprite.png",
        meta=out_dir / "episode_meta.json",
    )

    # Idempotent skip — sentinel present means a prior run completed cleanly.
    if (out_dir / ".complete").exists():
        return bundle

    _require("ffmpeg")
    _require("ffprobe")

    ep = get_episode_meta(dataset_root, episode_index)
    camera = camera_key or ep.camera_keys[0]
    channels = proprio_channels if proprio_channels is not None else [_default_state_dim(dataset_root)]
    duration = ep.to_timestamp - ep.from_timestamp

    # Resolve the data parquet and camera video with the same fail-loud
    # single-chunk contract the reader enforces on meta/episodes (issue #3):
    # a data/video file that spans >1 chunk/file would be sliced/seeked with
    # global indices that overrun file-000 and silently corrupt the bundle.
    # Resolved before ffmpeg so a multi-file dataset raises without doing work
    # or leaving a partial output dir.
    data_pq = _single_media_file(dataset_root / "data", "*.parquet", "data parquet")
    src_mp4 = _single_media_file(dataset_root / "videos" / camera, "*.mp4", "episode video")

    out_dir.mkdir(parents=True, exist_ok=True)

    _trim_clip(src_mp4, bundle.clip, ep.from_timestamp, duration)
    _generate_sprite(bundle.clip, bundle.sprite, duration)

    proprio = _extract_proprio(
        data_pq, ep.dataset_from_index, ep.dataset_to_index, channels
    )
    bundle.proprio.write_text(json.dumps(proprio))

    total_frames = _ffprobe_frame_count(bundle.clip)  # authoritative, from the clip
    bundle.meta.write_text(json.dumps({
        "episode_index": episode_index,
        "fps": ep.fps,
        "total_frames": total_frames,
        "dataset_from_index": ep.dataset_from_index,
        "camera": camera,
        "task": ep.task,
    }))

    # Completion sentinel — written last so partial/crashed runs leave no .complete.
    (out_dir / ".complete").write_text("1")

    return bundle
