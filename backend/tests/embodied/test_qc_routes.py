"""Quality scoring routes for temporal segment annotations."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.embodied.routes import router


@pytest.fixture
def qc_client(tmp_path, monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "ann"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post_segments(client: TestClient, annotator_id: str, segments: list[dict]) -> None:
    body = {
        "episode_id": "demo_episode",
        "annotator_id": annotator_id,
        "segments": [
            {
                "annotator_id": annotator_id,
                "episode_index": 0,
                **segment,
            }
            for segment in segments
        ],
    }
    r = client.post(
        "/api/embodied/segments",
        headers={"X-Annotator-Id": annotator_id},
        json=body,
    )
    assert r.status_code == 200, r.text


def test_demo_qc_scores_perfect_annotator_against_gold(qc_client):
    annotator = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _post_segments(
        qc_client,
        annotator,
        [
            {"start_frame": 0, "end_frame": 25, "skill_id": "reach"},
            {"start_frame": 25, "end_frame": 95, "skill_id": "grasp"},
            {"start_frame": 95, "end_frame": 167, "skill_id": "place"},
        ],
    )

    r = qc_client.get("/api/embodied/datasets/demo/episodes/0/qc")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset_id"] == "demo"
    assert body["episode_index"] == 0
    assert body["gold_count"] == 3
    assert len(body["annotators"]) == 1
    score = body["annotators"][0]
    assert score["annotator_id"] == annotator
    assert score["segment_count"] == 3
    assert score["matched_count"] == 3
    assert score["false_positive_count"] == 0
    assert score["miss_count"] == 0
    assert score["posterior_mean"] == pytest.approx(0.875)
    assert score["per_skill_iou"] == {
        "grasp": pytest.approx(1.0),
        "place": pytest.approx(1.0),
        "reach": pytest.approx(1.0),
    }


def test_demo_qc_counts_misses_and_false_positives(qc_client):
    annotator = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    _post_segments(
        qc_client,
        annotator,
        [
            {"start_frame": 0, "end_frame": 25, "skill_id": "reach"},
            {"start_frame": 120, "end_frame": 150, "skill_id": "handover"},
        ],
    )

    r = qc_client.get("/api/embodied/datasets/demo/episodes/0/qc")

    assert r.status_code == 200, r.text
    score = r.json()["annotators"][0]
    assert score["matched_count"] == 1
    assert score["false_positive_count"] == 1
    assert score["miss_count"] == 2
    assert score["posterior_alpha"] == pytest.approx(1.5)
    assert score["posterior_beta"] == pytest.approx(3.5)
    assert score["posterior_mean"] == pytest.approx(0.3)
