"""Real LeRobot dataset ingest for the embodied platform (Workstream C).

Parses a LeRobot dataset *root* given a local path (``file://`` URI or a plain
path) using only the standard library: ``meta/info.json`` for dataset-level
metadata and ``meta/episodes.jsonl`` (LeRobot v2 layout — one JSON object per
line with ``episode_index``, ``length``, ``tasks``) for per-episode records.

The v3 layout stores episode metadata as ``meta/episodes/*.parquet`` instead.
Reading parquet would require ``pyarrow`` (a new dependency we deliberately do
not add); when only parquet is present we raise :class:`UnsupportedDatasetError`
(a catchable :class:`IngestError`) so the import job records a clear, actionable
failure that a later build can make pluggable.

Every failure mode — path traversal, missing/non-directory root, missing or
malformed meta files, degenerate episode rows, oversized datasets — raises
:class:`IngestError`. Callers run this *before* mutating any shared state so a
failed parse can never partially materialize a dataset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlparse


# Sane upper bound so a hostile or accidentally-huge episodes.jsonl cannot
# balloon the shared state.json. Callers may lower it.
DEFAULT_MAX_EPISODES = 100_000

# meta/info.json is a small metadata document (fps, robot_type, counts). Cap its
# on-disk size before reading so a hostile multi-GB info.json cannot be loaded
# whole into memory via json.load (memory DoS). 1 MiB is orders of magnitude
# above any legitimate info.json.
MAX_INFO_JSON_BYTES = 1 << 20  # 1 MiB

# Single generic message for every "this path is not a usable dataset root"
# failure (missing target, non-directory, missing meta/ dir). These messages are
# persisted on the import job and surfaced via the *unauthenticated* GET /imports
# feed, so they must not echo the resolved/canonical host path (which leaks
# symlink targets) and must not distinguish not-found vs is-a-file vs missing-meta
# (which forms an arbitrary-path existence/type oracle). All three collapse to
# this one identical string.
_BAD_ROOT_MSG = "source is not a readable LeRobot dataset root"


class IngestError(Exception):
    """Any recoverable failure while parsing a LeRobot dataset root.

    Callers catch this to transition an import job to ``failed`` with a clear
    message instead of surfacing an unhandled 500.
    """


class UnsupportedDatasetError(IngestError):
    """The dataset layout is recognized but cannot be parsed without new deps.

    Currently raised for v3 parquet-only episode metadata when ``pyarrow`` is
    unavailable. Pluggable later behind an optional dependency.
    """


@dataclass(frozen=True)
class IngestEpisode:
    episode_id: str
    frame_count: int
    tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IngestResult:
    dataset_path: str
    fps: int | None
    total_episodes: int
    robot_type: str | None
    codebase_version: str | None
    episodes: list[IngestEpisode] = field(default_factory=list)


def _resolve_local_root(source_uri: str) -> Path:
    """Turn a ``file://`` URI or plain path into a guarded, existing directory.

    Rejects traversal, non-existent targets and non-directories. We resolve the
    path (collapsing any ``..``) and then re-check existence + is_dir() on the
    resolved form so a crafted ``a/../../etc`` cannot escape via the literal
    string — the filesystem only ever sees the canonical path.
    """
    raw = (source_uri or "").strip()
    if not raw:
        raise IngestError("source_uri is empty")

    if raw.startswith("file://"):
        parsed = urlparse(raw)
        # urlparse puts the path after the (empty) netloc; unquote %20 etc.
        candidate = unquote(parsed.path)
        if not candidate:
            raise IngestError(f"file:// URI has no path: {source_uri}")
    elif "://" in raw:
        scheme = raw.split("://", 1)[0]
        raise IngestError(
            f"unsupported source scheme {scheme!r}: only local file:// paths are ingestable"
        )
    else:
        candidate = raw

    try:
        resolved = Path(candidate).resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
        # strict=True raises FileNotFoundError for a missing target; RuntimeError
        # guards against symlink loops; ValueError covers an embedded NUL byte in
        # the path ('embedded null byte'). All become a clean, catchable
        # IngestError so the import job fails instead of surfacing a 500. The
        # message stays generic (no path, indistinguishable from the is-a-file and
        # missing-meta cases) so the persisted job can't act as a path oracle.
        raise IngestError(_BAD_ROOT_MSG) from exc

    if not resolved.is_dir():
        raise IngestError(_BAD_ROOT_MSG)
    return resolved


def _read_info(meta_dir: Path) -> dict:
    info_path = meta_dir / "info.json"
    if not info_path.is_file():
        raise IngestError("missing meta/info.json")
    try:
        size = info_path.stat().st_size
    except OSError as exc:
        raise IngestError(f"could not stat meta/info.json: {exc}") from exc
    if size > MAX_INFO_JSON_BYTES:
        raise IngestError(
            f"meta/info.json is too large ({size} bytes > {MAX_INFO_JSON_BYTES} cap)"
        )
    try:
        with info_path.open() as f:
            info = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise IngestError(f"meta/info.json is not valid JSON: {exc}") from exc
    if not isinstance(info, dict):
        raise IngestError("meta/info.json must be a JSON object")
    return info


def _coerce_int(value: object, *, field_name: str) -> int:
    # bool is an int subclass; reject it so a stray `true` is not read as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestError(f"{field_name} must be an integer, got {type(value).__name__}")
    return value


def _parse_episode_row(obj: object, *, line_no: int) -> IngestEpisode:
    if not isinstance(obj, dict):
        raise IngestError(f"meta/episodes.jsonl line {line_no} is not a JSON object")

    if "episode_index" not in obj:
        raise IngestError(f"meta/episodes.jsonl line {line_no} missing episode_index")
    index = _coerce_int(obj["episode_index"], field_name=f"episode_index (line {line_no})")
    if index < 0:
        raise IngestError(f"meta/episodes.jsonl line {line_no} has negative episode_index")

    if "length" not in obj:
        raise IngestError(f"meta/episodes.jsonl line {line_no} missing length")
    length = _coerce_int(obj["length"], field_name=f"length (line {line_no})")
    if length < 0:
        raise IngestError(f"meta/episodes.jsonl line {line_no} has negative length")

    raw_tasks = obj.get("tasks", [])
    if raw_tasks is None:
        tasks: list[str] = []
    elif isinstance(raw_tasks, str):
        tasks = [raw_tasks]
    elif isinstance(raw_tasks, list) and all(isinstance(t, str) for t in raw_tasks):
        tasks = list(raw_tasks)
    else:
        raise IngestError(f"meta/episodes.jsonl line {line_no} has malformed tasks")

    return IngestEpisode(
        episode_id=f"episode_{index:06d}",
        frame_count=length,
        tasks=tasks,
    )


def _read_episodes(meta_dir: Path, *, max_episodes: int) -> list[IngestEpisode]:
    jsonl_path = meta_dir / "episodes.jsonl"
    if jsonl_path.is_file():
        return _read_episodes_jsonl(jsonl_path, max_episodes=max_episodes)

    # v3 layout: episode metadata lives in parquet shards under meta/episodes/.
    parquet_dir = meta_dir / "episodes"
    if parquet_dir.is_dir() and any(parquet_dir.glob("*.parquet")):
        _require_pyarrow()
        # If pyarrow is importable we still do not implement the parquet reader
        # here — that is the pluggable extension point. Fail loud rather than
        # silently returning zero episodes.
        raise UnsupportedDatasetError(
            "parquet (v3) episode metadata reading is not implemented yet"
        )

    raise IngestError("missing meta/episodes.jsonl")


def _require_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise UnsupportedDatasetError(
            "dataset uses parquet (v3) episode metadata but pyarrow is unavailable; "
            "install pyarrow or provide a v2 meta/episodes.jsonl"
        ) from exc


def _read_episodes_jsonl(jsonl_path: Path, *, max_episodes: int) -> list[IngestEpisode]:
    episodes: list[IngestEpisode] = []
    try:
        with jsonl_path.open() as f:
            for line_no, raw_line in enumerate(f, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue  # blank/whitespace lines are not records.
                if len(episodes) >= max_episodes:
                    raise IngestError(
                        f"episode count exceeds cap of {max_episodes}"
                    )
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise IngestError(
                        f"meta/episodes.jsonl line {line_no} is not valid JSON: {exc}"
                    ) from exc
                episodes.append(_parse_episode_row(obj, line_no=line_no))
    except OSError as exc:
        raise IngestError(f"could not read meta/episodes.jsonl: {exc}") from exc

    if not episodes:
        raise IngestError("meta/episodes.jsonl contains no episodes")
    return episodes


def parse_lerobot_root(source_uri: str, *, max_episodes: int = DEFAULT_MAX_EPISODES) -> IngestResult:
    """Parse a local LeRobot dataset root into a structured :class:`IngestResult`.

    Accepts a ``file://`` URI or a plain local path. Raises :class:`IngestError`
    (or its :class:`UnsupportedDatasetError` subclass) on any failure; never
    returns a partially-parsed result.
    """
    root = _resolve_local_root(source_uri)
    meta_dir = root / "meta"
    if not meta_dir.is_dir():
        # Same generic message as the missing/non-directory root cases: a present
        # dir without meta/ must be indistinguishable from an absent one so this
        # cannot probe arbitrary-path existence/type, and no canonical path leaks.
        raise IngestError(_BAD_ROOT_MSG)

    info = _read_info(meta_dir)
    episodes = _read_episodes(meta_dir, max_episodes=max_episodes)

    fps = info.get("fps")
    if fps is not None and (isinstance(fps, bool) or not isinstance(fps, (int, float))):
        raise IngestError("meta/info.json fps must be a number")
    # json.load accepts bare NaN/Infinity tokens by default; reject them here so
    # int(fps) below cannot raise ValueError/OverflowError outside the caller's
    # IngestError catch (which would surface as a 500). A non-finite fps is a
    # clean, catchable parse failure.
    if isinstance(fps, float) and not math.isfinite(fps):
        raise IngestError("meta/info.json fps must be finite")

    robot_type = info.get("robot_type")
    if robot_type is not None and not isinstance(robot_type, str):
        raise IngestError("meta/info.json robot_type must be a string")

    codebase_version = info.get("codebase_version")
    if codebase_version is not None and not isinstance(codebase_version, str):
        raise IngestError("meta/info.json codebase_version must be a string")

    return IngestResult(
        dataset_path=str(root),
        fps=int(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else None,
        total_episodes=len(episodes),
        robot_type=robot_type,
        codebase_version=codebase_version,
        episodes=episodes,
    )
