"""Quality scoring routes for temporal segment annotations."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.embodied.routes import principal_annotator_id, router


def _auth(actor: str, role: str = "annotator") -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Actor": actor,
        "X-Embodied-Role": role,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


@pytest.fixture
def qc_client(tmp_path, monkeypatch):
    monkeypatch.delenv("XINGJU_EMBODIED_DATASET_ROOT", raising=False)
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path / "ann"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post_segments(client: TestClient, actor: str, segments: list[dict]) -> None:
    annotator_id = str(principal_annotator_id(actor))
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
        headers=_auth(actor),
        json=body,
    )
    assert r.status_code == 200, r.text


def test_demo_qc_scores_perfect_annotator_against_gold(qc_client):
    actor = "alice"
    annotator = str(principal_annotator_id(actor))
    _post_segments(
        qc_client,
        actor,
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


def test_score_annotator_caps_pathological_segment_lists():
    """The exact DP matcher recurses once per annotator segment and memoizes on
    (index, gold-mask): the <=22 gate bounds only the GOLD side, so an
    uncapped hostile/buggy annotator list drives unbounded recursion and
    lru_cache growth (RecursionError 500 at ~1000 segments, worse beyond).
    Above ANNOTATOR_SEGMENTS_CAP the scorer must truncate deterministically,
    flag the report, and count the overflow against the annotator
    (fail-closed) — not crash or hang."""
    from uuid import UUID

    from api.embodied.qc import ANNOTATOR_SEGMENTS_CAP, score_annotator
    from api.embodied.schema import SubtaskSegment

    zero = UUID("00000000-0000-0000-0000-000000000000")

    def seg(start: int, end: int, skill: str) -> SubtaskSegment:
        return SubtaskSegment(
            annotator_id=zero, episode_index=0,
            start_frame=start, end_frame=end, skill_id=skill,
        )

    gold = [seg(0, 10, "reach"), seg(10, 20, "grasp")]
    flood = [seg(i, i + 5, "reach") for i in range(2000)]

    report = score_annotator("ann-flood", flood, gold, iou_success_threshold=0.7)

    assert report["annotator_segments_capped"] is True
    # segment_count reports the TRUE submitted count, not the scored prefix.
    assert report["segment_count"] == 2000
    # Overflow segments are unscored but not free: they count as failures.
    overflow = 2000 - ANNOTATOR_SEGMENTS_CAP
    assert report["false_positive_count"] >= overflow
    assert report["posterior_beta"] >= overflow
    # Deterministic: the same input yields the identical report.
    again = score_annotator("ann-flood", flood, gold, iou_success_threshold=0.7)
    assert again == report


def test_score_annotator_below_cap_is_not_flagged():
    """An ordinary segment list must score exactly as before, unflagged."""
    from uuid import UUID

    from api.embodied.qc import score_annotator
    from api.embodied.schema import SubtaskSegment

    zero = UUID("00000000-0000-0000-0000-000000000000")
    gold = [SubtaskSegment(annotator_id=zero, episode_index=0,
                           start_frame=0, end_frame=10, skill_id="reach")]
    report = score_annotator("ann-ok", list(gold), gold, iou_success_threshold=0.7)
    assert report["annotator_segments_capped"] is False
    assert report["matched_count"] == 1
    assert report["false_positive_count"] == 0


def test_demo_qc_counts_misses_and_false_positives(qc_client):
    actor = "bob"
    annotator = str(principal_annotator_id(actor))
    _post_segments(
        qc_client,
        actor,
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
