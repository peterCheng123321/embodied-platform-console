"""Tests for the embodied dataset registry (datasets.py)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.embodied.datasets import (
    DatasetInfo,
    list_datasets,
    dataset_root_for,
)
from tests.embodied.fixtures import build_synthetic_lerobot_dataset


def test_demo_always_present(monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    infos = list_datasets()
    ids = [d.id for d in infos]
    assert "demo" in ids
    demo = next(d for d in infos if d.id == "demo")
    assert isinstance(demo, DatasetInfo)
    assert demo.kind == "demo"


def test_recorded_absent_without_env(monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    ids = [d.id for d in list_datasets()]
    assert "recorded" not in ids


def test_recorded_present_with_env(tmp_path, monkeypatch):
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=2, fps=10)
    monkeypatch.setenv("XINGJU_EMBODIED_DATASET_ROOT", str(root))
    infos = list_datasets()
    rec = next((d for d in infos if d.id == "recorded"), None)
    assert rec is not None
    assert rec.kind == "lerobot"
    assert rec.episode_count == 2


def test_dataset_root_for_demo_is_builtin_assets(monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    root = dataset_root_for("demo")
    assert root.name == "embodied"
    assert root.parent.name == "assets"


def test_dataset_root_for_recorded(tmp_path, monkeypatch):
    root = build_synthetic_lerobot_dataset(tmp_path, n_episodes=1, fps=10)
    monkeypatch.setenv("XINGJU_EMBODIED_DATASET_ROOT", str(root))
    assert dataset_root_for("recorded") == root


def test_dataset_root_for_unknown_raises_404(monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    with pytest.raises(HTTPException) as exc:
        dataset_root_for("nope")
    assert exc.value.status_code == 404
