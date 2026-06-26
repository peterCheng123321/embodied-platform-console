"""Unit tests for the real LeRobot dataset ingest (Workstream C).

These pin the parse contract that POST /imports relies on: a local LeRobot v2
root (file:// or plain path) is parsed into a structured result, and every
hostile/degenerate input raises a single catchable IngestError rather than
leaking a 500 or partially-parsed state to the caller.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.embodied_platform.ingest import (
    IngestError,
    UnsupportedDatasetError,
    parse_lerobot_root,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "lerobot_demo"


def _write_dataset(root: Path, info: dict, episode_lines: list[dict]) -> Path:
    meta = root / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "info.json").write_text(json.dumps(info))
    with (meta / "episodes.jsonl").open("w") as f:
        for line in episode_lines:
            f.write(json.dumps(line) + "\n")
    return root


def test_parses_fixture_into_structured_result():
    result = parse_lerobot_root(str(FIXTURE_ROOT))

    assert result.fps == 30
    assert result.total_episodes == 3
    assert result.robot_type == "so100"
    assert result.codebase_version == "v2.0"
    assert [ep.frame_count for ep in result.episodes] == [120, 140, 100]
    # episode_id is derived deterministically from episode_index.
    assert [ep.episode_id for ep in result.episodes] == [
        "episode_000000",
        "episode_000001",
        "episode_000002",
    ]
    assert result.episodes[1].tasks == ["pick up the red cube", "place it in the bin"]


def test_accepts_file_uri_scheme():
    result = parse_lerobot_root(FIXTURE_ROOT.as_uri())
    assert result.total_episodes == 3
    assert len(result.episodes) == 3


def test_robot_type_absent_is_none(tmp_path):
    root = _write_dataset(
        tmp_path / "ds",
        {"fps": 20, "total_episodes": 1},
        [{"episode_index": 0, "length": 50, "tasks": []}],
    )
    result = parse_lerobot_root(str(root))
    assert result.robot_type is None
    assert result.fps == 20
    assert result.episodes[0].frame_count == 50


def test_rejects_path_traversal():
    with pytest.raises(IngestError):
        parse_lerobot_root("file:///etc/../etc/passwd/../../tmp/lerobot_does_not_exist_xyz")


def test_rejects_nonexistent_root(tmp_path):
    with pytest.raises(IngestError):
        parse_lerobot_root(str(tmp_path / "no_such_dataset"))


def test_rejects_file_as_root(tmp_path):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("hello")
    with pytest.raises(IngestError):
        parse_lerobot_root(str(f))


def test_missing_info_json_raises(tmp_path):
    root = tmp_path / "ds"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "episodes.jsonl").write_text(
        json.dumps({"episode_index": 0, "length": 10, "tasks": []}) + "\n"
    )
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root))


def test_missing_episodes_jsonl_raises(tmp_path):
    root = tmp_path / "ds"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text(json.dumps({"fps": 30, "total_episodes": 0}))
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root))


def test_malformed_info_json_raises(tmp_path):
    root = tmp_path / "ds"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text("{ not json")
    (root / "meta" / "episodes.jsonl").write_text("")
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root))


def test_malformed_episodes_line_raises(tmp_path):
    root = _write_dataset(
        tmp_path / "ds",
        {"fps": 30, "total_episodes": 1},
        [],
    )
    (root / "meta" / "episodes.jsonl").write_text("{ this is not json }\n")
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root))


def test_negative_length_raises(tmp_path):
    root = _write_dataset(
        tmp_path / "ds",
        {"fps": 30, "total_episodes": 1},
        [{"episode_index": 0, "length": -5, "tasks": []}],
    )
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root))


def test_blank_episodes_lines_are_skipped(tmp_path):
    root = _write_dataset(
        tmp_path / "ds",
        {"fps": 30, "total_episodes": 2},
        [{"episode_index": 0, "length": 10, "tasks": []}],
    )
    # A trailing blank line / interior whitespace line must not be parsed as JSON.
    with (root / "meta" / "episodes.jsonl").open("a") as f:
        f.write("\n   \n")
        f.write(json.dumps({"episode_index": 1, "length": 20, "tasks": []}) + "\n")
    result = parse_lerobot_root(str(root))
    assert result.total_episodes == 2
    assert [ep.frame_count for ep in result.episodes] == [10, 20]


def test_episode_count_cap_enforced(tmp_path):
    lines = [{"episode_index": i, "length": 1, "tasks": []} for i in range(5)]
    root = _write_dataset(tmp_path / "ds", {"fps": 30, "total_episodes": 5}, lines)
    with pytest.raises(IngestError):
        parse_lerobot_root(str(root), max_episodes=3)


def test_oversized_info_json_is_rejected_before_load(tmp_path):
    """An attacker-supplied multi-MiB info.json must be rejected by a cheap
    size check before json.load reads it whole into memory (memory DoS). Pin the
    cap: an info.json above MAX_INFO_JSON_BYTES raises IngestError, and the
    failure must be detected without parsing (a giant blob of non-JSON bytes
    still raises the *size* error, proving json.load was never reached)."""
    from api.embodied_platform.ingest import MAX_INFO_JSON_BYTES

    root = tmp_path / "ds"
    meta = root / "meta"
    meta.mkdir(parents=True)
    # Non-JSON padding past the cap: if json.load ran it would raise a *decode*
    # error; the size guard must fire first with a size message instead.
    (meta / "info.json").write_text("x" * (MAX_INFO_JSON_BYTES + 1))
    (meta / "episodes.jsonl").write_text(
        json.dumps({"episode_index": 0, "length": 10, "tasks": []}) + "\n"
    )

    with pytest.raises(IngestError) as excinfo:
        parse_lerobot_root(str(root))
    assert "too large" in str(excinfo.value)


def test_existing_file_root_error_message_leaks_no_host_path(tmp_path):
    """F4: the import is an arbitrary-path existence/type oracle, and the resolved
    canonical HOST PATH must not leak into the failure message — that message is
    persisted on the import job and surfaced via the UNAUTHENTICATED GET /imports
    feed (leaking symlink targets / filesystem layout). A path that resolves to an
    existing host FILE (not a dataset dir) must raise the single generic
    _BAD_ROOT_MSG, identical to the not-found and missing-meta cases, with NO trace
    of the resolved path — so the feed cannot be used as a path oracle.

    Pins the SANITIZED message specifically (the existing 'rejects file as root'
    test only checks that it raises)."""
    from api.embodied_platform.ingest import _BAD_ROOT_MSG

    secret = tmp_path / "secret-host-file.txt"
    secret.write_text("sensitive host contents")

    with pytest.raises(IngestError) as excinfo:
        parse_lerobot_root(str(secret))

    message = str(excinfo.value)
    # Exactly the generic message — indistinguishable from not-found / missing-meta.
    assert message == _BAD_ROOT_MSG
    # The resolved host path (and its basename) must NOT appear in the message.
    assert str(secret) not in message
    assert "secret-host-file" not in message
    assert str(tmp_path) not in message


def test_parquet_only_without_pyarrow_raises_unsupported(tmp_path, monkeypatch):
    root = tmp_path / "ds"
    episodes_dir = root / "meta" / "episodes"
    episodes_dir.mkdir(parents=True)
    (root / "meta" / "info.json").write_text(
        json.dumps({"fps": 30, "total_episodes": 1, "codebase_version": "v3.0"})
    )
    (episodes_dir / "chunk-000.parquet").write_bytes(b"PAR1stub")

    # Simulate pyarrow being unavailable in this environment.
    import builtins

    real_import = builtins.__import__

    def _no_pyarrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyarrow)

    with pytest.raises(UnsupportedDatasetError):
        parse_lerobot_root(str(root))
    # UnsupportedDatasetError must be catchable as the generic IngestError too.
    assert issubclass(UnsupportedDatasetError, IngestError)
