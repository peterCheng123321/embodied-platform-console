"""Tests for api.embodied.lerobot_reader against the synthetic fixture."""
from __future__ import annotations

import pytest

from api.embodied.lerobot_reader import (
    EpisodeMeta,
    get_episode_meta,
    list_episodes,
)
from tests.embodied.fixtures import _EP_LEN, build_synthetic_lerobot_dataset


def test_list_episodes_returns_all_with_correct_meta(tmp_path):
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=2, fps=10, with_video=False)
    eps = list_episodes(root)
    assert [e.episode_index for e in eps] == [0, 1]
    assert all(isinstance(e, EpisodeMeta) for e in eps)

    e0 = eps[0]
    assert e0.fps == 10.0
    assert e0.length == _EP_LEN
    assert e0.task == "pick up the cube"
    assert e0.camera_keys == ["observation.images.exterior_image_1_left"]
    # Offsets into the concatenated data parquet for episode 0.
    assert e0.dataset_from_index == 0
    assert e0.dataset_to_index == _EP_LEN
    # Per-episode video seek window (seconds) for the primary camera.
    assert e0.from_timestamp == 0.0
    assert e0.to_timestamp == pytest.approx(0.8)

    e1 = eps[1]
    assert e1.episode_index == 1
    assert e1.dataset_from_index == _EP_LEN
    assert e1.dataset_to_index == 2 * _EP_LEN
    assert e1.from_timestamp == pytest.approx(0.8)


def test_get_episode_meta_single(tmp_path):
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=2, fps=10, with_video=False)
    e = get_episode_meta(root, 1)
    assert isinstance(e, EpisodeMeta)
    assert e.episode_index == 1
    assert e.task == "pick up the cube"
    assert e.camera_keys == ["observation.images.exterior_image_1_left"]


def test_get_episode_meta_not_found_raises(tmp_path):
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=2, fps=10, with_video=False)
    with pytest.raises(IndexError):
        get_episode_meta(root, 99)


def test_get_episode_meta_is_by_value_not_position(tmp_path):
    """get_episode_meta must do value-lookup on episode_index, not positional indexing.

    Reasoning: a naive positional implementation — list_episodes(root)[episode_index]
    — would fail this test in both directions:
      - list_episodes(root)[0] returns the first episode (index 5) instead of raising
      - list_episodes(root)[6] raises IndexError (list len 2) instead of returning ep 6

    The real value-lookup implementation does the opposite: index 6 returns the second
    episode, and index 0 raises because no episode with episode_index==0 exists.
    """
    # Fixture has episode_index values [5, 6]; data indices are still 0-based.
    root = build_synthetic_lerobot_dataset(
        tmp_path, n_episodes=2, fps=10, start_index=5, with_video=False
    )

    # episode_index=6 is the SECOND episode: dataset_from_index==_EP_LEN, length==_EP_LEN.
    ep6 = get_episode_meta(root, 6)
    assert ep6.episode_index == 6
    assert ep6.dataset_from_index == _EP_LEN
    assert ep6.length == _EP_LEN

    # episode_index=0 does not exist — must raise IndexError, not return episode 5.
    with pytest.raises(IndexError):
        get_episode_meta(root, 0)
