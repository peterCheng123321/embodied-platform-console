"""Integration tests for hosting the temporal labeler inside the platform app."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_host_serves_labeler_and_embodied_api_same_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "segments"))
    monkeypatch.setenv("XINGJU_EMBODIED_CACHE_ROOT", str(tmp_path / "cache"))

    from api.main import app

    client = TestClient(app)

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/app/"

    labeler = client.get("/labeler/")
    assert labeler.status_code == 200
    # Version-agnostic: the labeler references its JS bundle. (Don't pin the
    # ?v=NN cache-bust — it changes on every front-end edit.)
    assert "assets/embodied/embodied.js" in labeler.text
    assert "127.0.0.1:8001" not in labeler.text

    datasets = client.get("/api/embodied/datasets")
    assert datasets.status_code == 200
    assert {item["id"] for item in datasets.json()} >= {"demo"}

    episodes = client.get("/api/embodied/datasets/demo/episodes")
    assert episodes.status_code == 200
    assert episodes.json()[0]["episode_index"] == 0

    bundle = client.get("/api/embodied/datasets/demo/episodes/0")
    assert bundle.status_code == 200
    body = bundle.json()
    assert body["video_url"] == "/embodied-assets/demo_episode.mp4"
    assert body["sprite_url"] == "/embodied-assets/sprite.png"
    assert body["proprio_url"] == "/embodied-assets/demo_episode.gripper.json"

    asset = client.get(body["video_url"])
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("video/mp4")


def test_embodied_cache_mount_honors_cache_root_env(tmp_path, monkeypatch):
    custom_cache = tmp_path / "custom-cache"
    monkeypatch.setenv("XINGJU_EMBODIED_CACHE_ROOT", str(custom_cache))

    import api.main as main

    assert main._embodied_cache_dir() == custom_cache
