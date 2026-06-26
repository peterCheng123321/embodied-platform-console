"""Tests for GET /datasets, /datasets/{id}/episodes, /datasets/{id}/episodes/{ix}."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from api.embodied.routes import router
from tests.embodied.fixtures import build_synthetic_lerobot_dataset


@pytest.fixture
def recorded_client(tmp_path, monkeypatch):
    """App with the embodied router + cache static mount, env pointed at a
    synthetic recorded dataset. Mirrors the wiring main.py performs."""
    ds_root = build_synthetic_lerobot_dataset(tmp_path / "ds", n_episodes=2, fps=10)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    monkeypatch.setenv("XINGJU_EMBODIED_DATASET_ROOT", str(ds_root))
    monkeypatch.setenv("XINGJU_EMBODIED_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "ann"))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)

    app = FastAPI()
    app.include_router(router)
    app.mount(
        "/embodied-cache",
        StaticFiles(directory=str(cache_root), check_dir=False),
        name="embodied-cache",
    )
    return TestClient(app), ds_root, cache_root


def test_list_datasets_includes_demo_and_recorded(recorded_client):
    client, _, _ = recorded_client
    r = client.get("/api/embodied/datasets")
    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json()]
    assert "demo" in ids
    assert "recorded" in ids


def test_list_episodes_for_recorded(recorded_client):
    client, _, _ = recorded_client
    r = client.get("/api/embodied/datasets/recorded/episodes")
    assert r.status_code == 200, r.text
    eps = r.json()
    assert len(eps) == 2
    ep0 = eps[0]
    assert ep0["episode_index"] == 0
    assert "task" in ep0 and "length" in ep0 and "fps" in ep0
    assert ep0["has_annotations"] is False


def test_list_episodes_has_annotations_true_when_annotator_file_present(recorded_client):
    client, ds_root, _ = recorded_client
    annotator_id = "11111111-1111-1111-1111-111111111111"
    ann_dir = ds_root / "meta" / "annotations" / annotator_id
    ann_dir.mkdir(parents=True, exist_ok=True)
    seg_line = (
        f'{{"annotator_id":"{annotator_id}",'
        '"episode_index":0,"start_frame":0,"end_frame":2,"skill_id":"reach"}\n'
    )
    (ann_dir / "subtask_segments.v1.jsonl").write_text(seg_line)
    r = client.get("/api/embodied/datasets/recorded/episodes")
    assert r.status_code == 200, r.text
    eps = r.json()
    ep0 = next(e for e in eps if e["episode_index"] == 0)
    assert ep0["has_annotations"] is True
    # Episode 1 has no annotation — must remain False.
    ep1 = next(e for e in eps if e["episode_index"] == 1)
    assert ep1["has_annotations"] is False


def test_list_episodes_has_annotations_true_for_api_saved_segments(recorded_client):
    """Segments saved through POST /segments must flip has_annotations.

    WHY: the labeler addresses episodes as <dataset_id>_ep<episode_index>
    (embodied.js EPISODE_ID), so the episode list's annotated-marker is the
    only signal a labeler has that an episode is already done. If the flag
    ignored the API's own write store, every episode would forever show
    unannotated and labelers would double-label.
    """
    client, _, _ = recorded_client
    annotator_id = "22222222-2222-2222-2222-222222222222"
    r = client.post(
        "/api/embodied/segments",
        headers={"X-Annotator-Id": annotator_id},
        json={
            "episode_id": "recorded_ep1",
            "annotator_id": annotator_id,
            "segments": [{
                "annotator_id": annotator_id,
                "episode_index": 1,
                "start_frame": 0,
                "end_frame": 2,
                "skill_id": "reach",
            }],
        },
    )
    assert r.status_code == 200, r.text
    eps = client.get("/api/embodied/datasets/recorded/episodes").json()
    ep1 = next(e for e in eps if e["episode_index"] == 1)
    assert ep1["has_annotations"] is True
    ep0 = next(e for e in eps if e["episode_index"] == 0)
    assert ep0["has_annotations"] is False


def test_list_episodes_unknown_dataset_404(recorded_client):
    client, _, _ = recorded_client
    r = client.get("/api/embodied/datasets/bogus/episodes")
    assert r.status_code == 404


def test_get_episode_bundle_materializes(recorded_client):
    client, _, cache_root = recorded_client
    r = client.get("/api/embodied/datasets/recorded/episodes/0")
    assert r.status_code == 200, r.text
    body = r.json()
    # Bundle URLs point at the cache static mount.
    for key in ("video_url", "sprite_url", "proprio_url"):
        assert body[key].startswith("/embodied-cache/"), body[key]
    assert body["meta"]["episode_index"] == 0
    assert body["meta"]["fps"] == 10
    # gold is null when no _gold file exists.
    assert body["gold"] is None
    # The static file the URL names actually exists on disk now.
    rel = body["video_url"][len("/embodied-cache/"):]
    assert (cache_root / rel).exists()


def test_get_episode_bundle_is_idempotent(recorded_client):
    client, _, _ = recorded_client
    r1 = client.get("/api/embodied/datasets/recorded/episodes/0")
    r2 = client.get("/api/embodied/datasets/recorded/episodes/0")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["video_url"] == r2.json()["video_url"]


def test_get_episode_bundle_serves_via_static_mount(recorded_client):
    client, _, _ = recorded_client
    body = client.get("/api/embodied/datasets/recorded/episodes/0").json()
    # The clip is fetchable through the mounted static route.
    vr = client.get(body["video_url"])
    assert vr.status_code == 200
    assert int(vr.headers["content-length"]) > 0


def test_get_episode_bundle_gold_loaded_when_present(recorded_client):
    client, ds_root, _ = recorded_client
    gold_dir = ds_root / "meta" / "annotations" / "_gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    # First line is malformed (start_frame == end_frame violates the schema's
    # start<end invariant): one bad gold line must not 500 the whole episode
    # bundle — _load_gold documents skip-don't-500 and this pins it.
    bad_line = (
        '{"annotator_id":"00000000-0000-0000-0000-000000000000",'
        '"episode_index":0,"start_frame":3,"end_frame":3,"skill_id":"bad"}\n'
    )
    gold_line = (
        '{"annotator_id":"00000000-0000-0000-0000-000000000000",'
        '"episode_index":0,"start_frame":0,"end_frame":3,"skill_id":"reach"}\n'
    )
    (gold_dir / "subtask_segments.v1.jsonl").write_text(bad_line + gold_line)
    r = client.get("/api/embodied/datasets/recorded/episodes/0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gold"] is not None
    assert len(body["gold"]) == 1
    assert body["gold"][0]["skill_id"] == "reach"


def test_get_episode_bundle_unknown_dataset_404(recorded_client):
    client, _, _ = recorded_client
    r = client.get("/api/embodied/datasets/bogus/episodes/0")
    assert r.status_code == 404


def test_get_episode_bundle_out_of_range_404(recorded_client):
    """Out-of-range/negative indices are routine client states (deleted or
    renumbered episodes in a labeler URL), so they must map to 404 like every
    other miss — not leak get_episode_meta's IndexError as a 500."""
    client, _, _ = recorded_client
    for ix in (99, -1):
        r = client.get(f"/api/embodied/datasets/recorded/episodes/{ix}")
        assert r.status_code == 404, f"episodes/{ix}: {r.status_code} {r.text}"


def test_materialize_timeout_returns_503_and_releases_lock(recorded_client, monkeypatch):
    """A hung ffmpeg/ffprobe (TimeoutExpired) must surface as a clean 503 JSON
    detail — not an unhandled 500 — and the per-episode materialization lock
    must be RELEASED on the way out, so a follow-up request for the same
    episode gets the same clean error instead of deadlocking behind the dead
    pipeline."""
    import subprocess as subprocess_mod

    import api.embodied.episode_materializer as mat_mod

    client, _, _ = recorded_client
    # Pass the _require() PATH probe even on hosts without ffmpeg installed —
    # subprocess.run below never actually executes anything.
    monkeypatch.setattr(mat_mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def hanging_run(cmd, *args, **kwargs):
        raise subprocess_mod.TimeoutExpired(cmd, kwargs.get("timeout") or 0)

    monkeypatch.setattr(mat_mod.subprocess, "run", hanging_run)

    first = client.get("/api/embodied/datasets/recorded/episodes/0")
    assert first.status_code == 503, first.text
    assert "timed out" in first.json()["detail"]

    # Lock released: the second request re-attempts materialization and gets
    # the same clean 503 — it neither deadlocks nor serves a torn bundle.
    second = client.get("/api/embodied/datasets/recorded/episodes/0")
    assert second.status_code == 503, second.text
    assert "timed out" in second.json()["detail"]


def test_concurrent_bundle_requests_serialize_materialization(recorded_client, monkeypatch):
    """Two simultaneous first requests for the same uncached episode must not
    both run the ffmpeg pipeline: overlapping materialize() calls write the
    same clip/sprite with -y, and a torn bundle can then be sealed behind the
    .complete sentinel and served forever. The sentinel guards against
    crashes, not concurrency — the route must serialize per episode."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import api.embodied.routes as routes_mod

    client, _, _ = recorded_client
    real = routes_mod.materialize
    guard = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def tracking_materialize(*args, **kwargs):
        with guard:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.25)  # widen the race window for unserialized callers
            return real(*args, **kwargs)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(routes_mod, "materialize", tracking_materialize)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(client.get, "/api/embodied/datasets/recorded/episodes/0")
            for _ in range(2)
        ]
        responses = [f.result() for f in futures]
    assert all(r.status_code == 200 for r in responses)
    assert state["max_active"] == 1, "materialize() ran concurrently for the same episode"


def test_list_datasets_skips_recorded_when_root_missing(tmp_path, monkeypatch):
    """A stale/nonexistent XINGJU_EMBODIED_DATASET_ROOT (a plausible ops state
    the dev.sh env docs invite) must not 500 the registry and hide the
    always-available demo dataset; the recorded entry is skipped instead."""
    monkeypatch.setenv("XINGJU_EMBODIED_DATASET_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/api/embodied/datasets")
    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json()]
    assert "demo" in ids
    assert "recorded" not in ids


def test_platform_imported_dataset_is_available_to_labeler(tmp_path, monkeypatch):
    ds_root = build_synthetic_lerobot_dataset(tmp_path / "platform-ds", n_episodes=2, fps=10)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    monkeypatch.setenv("XINGJU_EMBODIED_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "ann"))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)

    from api.embodied_platform.repository import JsonRepository, empty_state

    state = empty_state()
    state["datasets"].append({
        "id": "ds_platform",
        "name": "warehouse-pick-v1",
        "modality": "vision_language_action",
        "robot_type": "mobile_manipulator",
        "storage_uri": ds_root.as_uri(),
        "description": None,
        "episode_count": 2,
        "created_at": "2026-06-14T00:00:00+00:00",
        "trained_ready": False,
    })
    JsonRepository(tmp_path / "platform" / "state.json").write(state)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    datasets = client.get("/api/embodied/datasets")
    assert datasets.status_code == 200, datasets.text
    platform = next(item for item in datasets.json() if item["id"] == "ds_platform")
    assert platform["label"] == "warehouse-pick-v1"
    assert platform["kind"] == "lerobot"
    assert platform["episode_count"] == 2

    episodes = client.get("/api/embodied/datasets/ds_platform/episodes")
    assert episodes.status_code == 200, episodes.text
    assert [item["episode_index"] for item in episodes.json()] == [0, 1]

    bundle = client.get("/api/embodied/datasets/ds_platform/episodes/1")
    assert bundle.status_code == 200, bundle.text
    assert bundle.json()["meta"]["episode_index"] == 1


def test_main_app_wiring_static_mounts_and_router():
    """Pin the REAL api.main app wiring (the other tests hand-build a mirror
    app): a typo'd mount path or wrong parents[] resolution in main.py would
    pass the whole fixture-built suite while every video URL 404s in the real
    app. Lifespan tolerates Postgres being down, so this runs anywhere."""
    from api.main import app as main_app

    with TestClient(main_app) as c:
        assert c.get("/embodied-assets/demo_episode.mp4").status_code == 200
        assert c.get("/api/embodied/datasets").status_code == 200


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    """App with the embodied router + the /embodied-assets mount pointing at the
    real built-in demo dir. No recorded dataset env — exercises the zero-config
    demo default, which is served off the hosted labeler assets, NOT the reader."""
    from pathlib import Path

    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    monkeypatch.setenv("XINGJU_EMBODIED_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "ann"))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)
    # Hosted labeler assets resolve from this test file:
    # tests/embodied/ -> tests/ -> backend/ -> repo root.
    demo_dir = Path(__file__).resolve().parents[3] / "apps" / "embodied-labeler" / "assets" / "embodied"

    app = FastAPI()
    app.include_router(router)
    app.mount(
        "/embodied-assets",
        StaticFiles(directory=str(demo_dir), check_dir=False),
        name="embodied-assets",
    )
    return TestClient(app)


def test_demo_episode_list_is_single_episode(demo_client):
    r = demo_client.get("/api/embodied/datasets/demo/episodes")
    assert r.status_code == 200, r.text
    eps = r.json()
    assert len(eps) == 1
    assert eps[0]["episode_index"] == 0
    assert eps[0]["fps"] == 15  # from assets/embodied/episode_meta.json
    assert eps[0]["length"] == 167


def test_demo_episode_bundle_served_from_assets(demo_client):
    r = demo_client.get("/api/embodied/datasets/demo/episodes/0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["video_url"] == "/embodied-assets/demo_episode.mp4"
    assert body["sprite_url"] == "/embodied-assets/sprite.png"
    assert body["proprio_url"] == "/embodied-assets/demo_episode.gripper.json"
    assert body["meta"]["episode_index"] == 0
    assert body["meta"]["total_frames"] == 167
    # demo gold is the legacy JSON array shape (no annotator_id).
    assert isinstance(body["gold"], list) and len(body["gold"]) == 3
    assert body["gold"][0]["skill_id"] == "reach"
    # The video is actually fetchable through the mounted static route.
    vr = demo_client.get(body["video_url"])
    assert vr.status_code == 200
    assert int(vr.headers["content-length"]) > 0


def test_demo_episode_out_of_range_404(demo_client):
    r = demo_client.get("/api/embodied/datasets/demo/episodes/1")
    assert r.status_code == 404


def test_demo_has_annotations_true_for_api_saved_segments(demo_client):
    """Demo saves land under the HISTORICAL id 'demo_episode' (not 'demo_ep0')
    and must flip the demo episode's has_annotations.

    WHY: the demo branch carries bespoke logic — the legacy episode_id and an
    episode-scoped store where the directory name (not each line's
    episode_index stamp) is authoritative. Old frontends stamped indices
    inconsistently; a stamp re-filter would make the picker's annotated-marker
    lie False over real saved work.
    """
    annotator_id = "33333333-3333-3333-3333-333333333333"
    before = demo_client.get("/api/embodied/datasets/demo/episodes").json()
    assert before[0]["has_annotations"] is False
    r = demo_client.post(
        "/api/embodied/segments",
        headers={"X-Annotator-Id": annotator_id},
        json={
            "episode_id": "demo_episode",
            "annotator_id": annotator_id,
            "segments": [{
                "annotator_id": annotator_id,
                "episode_index": 0,
                "start_frame": 0,
                "end_frame": 5,
                "skill_id": "reach",
            }],
        },
    )
    assert r.status_code == 200, r.text
    after = demo_client.get("/api/embodied/datasets/demo/episodes").json()
    assert after[0]["has_annotations"] is True
