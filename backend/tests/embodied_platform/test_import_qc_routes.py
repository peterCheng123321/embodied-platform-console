"""Route-level tests for the real LeRobot import + dataset QC gate, ported from
the codex/embodied-platform branch.

POST /imports runs the ingest synchronously for LOCAL lerobot sources (parsing
happens BEFORE the repository write lock is taken); non-local sources keep the
console's original external status-PATCH contract. GET /datasets/{id}/qc reports
temporal-IoU coverage + inter-annotator agreement, and POST
/datasets/{id}/trained-ready flips the flag only when the QC gate passes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Local LeRobot v2 fixture (meta/info.json + meta/episodes.jsonl, 3 episodes).
LEROBOT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lerobot_demo"

# Marks tests that exercise JSON-file storage mechanics by definition (e.g. a
# bare NaN token that only ``json.load`` of a state FILE can produce — jsonb
# cannot hold one), so they only run in JSON-file mode.
_JSON_FILE_ONLY = pytest.mark.skipif(
    bool(os.environ.get("XINGJU_EMBODIED_PLATFORM_DSN", "").strip()),
    reason="exercises JSON-file storage mechanics; the PG equivalent lives in test_pg_repository.py",
)

LOGIN_PASSCODE = "pytest-login-passcode"


def _client(tmp_path, monkeypatch, *, raise_server_exceptions: bool = True) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import register_validation_handlers, router

    app = FastAPI()
    app.include_router(router)
    register_validation_handlers(app)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _no_raise_client(tmp_path, monkeypatch) -> TestClient:
    """Same wiring as ``_client`` but surfacing unhandled 500s as responses."""
    return _client(tmp_path, monkeypatch, raise_server_exceptions=False)


def _headers(role: str, actor: str) -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Role": role,
        "X-Embodied-Actor": actor,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _admin_headers() -> dict[str, str]:
    return _headers("admin", "pytest-admin")


def _ml_headers() -> dict[str, str]:
    return _headers("ml_engineer", "pytest-ml")


def _annotator_headers() -> dict[str, str]:
    return _headers("annotator", "labeler-a")


def _create_dataset(client: TestClient, name: str = "warehouse-pick-v1") -> dict:
    response = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": name,
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": f"file:///datasets/{name}",
            "description": "Pick and place episodes from demo fixtures.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_episode_with_frames(
    client: TestClient, dataset_id: str, episode_id: str, frame_count: int
) -> dict:
    response = client.post(
        "/api/embodied-platform/episodes",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset_id,
            "episode_id": episode_id,
            "robot_cell": "warehouse-a",
            "frame_count": frame_count,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _save_annotation(
    client: TestClient,
    dataset_id: str,
    episode_id: str,
    labels: list[dict],
    *,
    assignee: str = "annotator-a",
) -> dict:
    response = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset_id,
            "episode_id": episode_id,
            "task_type": "trajectory_segment",
            "assignee": assignee,
            "labels": labels,
            "status": "accepted",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _save_annotation_typed(
    client: TestClient,
    dataset_id: str,
    episode_id: str,
    labels: list[dict],
    *,
    task_type: str,
    assignee: str = "annotator-a",
) -> dict:
    response = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset_id,
            "episode_id": episode_id,
            "task_type": task_type,
            "assignee": assignee,
            "labels": labels,
            "status": "accepted",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _corrupt_state_client(tmp_path, monkeypatch, mutate, *, via_state_file: bool = False) -> TestClient:
    """Build a client whose persisted state has been corrupted via ``mutate``
    (a callable taking the state dict). By default the corruption is planted
    through the public repository surface (``get_repository().write``) —
    bypassing schema validation but staying backend-agnostic so the scenario is
    exercised in both JSON-file and Postgres mode. ``via_state_file=True`` writes
    state.json directly instead, for corruption that is NOT valid spec JSON
    (e.g. a bare NaN token) and therefore only exists in JSON-file mode."""
    from api.embodied_platform.routes import register_validation_handlers, router

    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")

    state = {
        "datasets": [
            {
                "id": "ds-corrupt",
                "name": "corrupt-ds",
                "modality": "vision_language_action",
                "robot_type": "so100",
                "storage_uri": "file:///datasets/corrupt",
                "description": None,
                "episode_count": 1,
                "created_at": "2026-05-30T00:00:00+00:00",
                "trained_ready": False,
            }
        ],
        "episodes": [
            {
                "id": "ep-corrupt",
                "dataset_id": "ds-corrupt",
                "episode_id": "episode-corrupt",
                "robot_cell": None,
                "frame_count": 100,
                "created_at": "2026-05-30T00:00:00+00:00",
            }
        ],
        "imports": [],
        "annotation_tasks": [
            {
                "id": "ann-corrupt",
                "dataset_id": "ds-corrupt",
                "episode_id": "episode-corrupt",
                "task_type": "trajectory_segment",
                "assignee": "annotator-a",
                "labels": [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}],
                "status": "accepted",
                "label_count": 1,
                "updated_at": "2026-05-30T00:00:00+00:00",
            }
        ],
        "training_jobs": [],
        "models": [],
        "simulation_jobs": [],
        "deployments": [],
        "learning_queue": [],
        "audit_events": [],
    }
    mutate(state)
    if via_state_file:
        # json.dumps default allow_nan=True can emit bare NaN/Infinity tokens
        # that only the file-backed repository's json.load will ever read back.
        (tmp_path / "state.json").write_text(json.dumps(state))
    else:
        from api.embodied_platform.repository import get_repository

        get_repository().write(state)

    app = FastAPI()
    app.include_router(router)
    register_validation_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


# --- dataset QC report + trained-ready gate ----------------------------------


def test_qc_report_reflects_coverage_and_agreement(tmp_path, monkeypatch):
    """GET /qc reports per-episode coverage and inter-annotator agreement so the
    data-quality flywheel is observable before any gating decision."""
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    # 100-frame episode fully covered (>= 0.9) by both annotators.
    _create_episode_with_frames(client, dataset["id"], "episode-100", 100)
    _save_annotation(
        client, dataset["id"], "episode-100",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-a",
    )
    _save_annotation(
        client, dataset["id"], "episode-100",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-b",
    )

    report = client.get(f"/api/embodied-platform/datasets/{dataset['id']}/qc")
    assert report.status_code == 200, report.text
    body = report.json()
    row = next(r for r in body["episodes"] if r["episode_id"] == "episode-100")
    assert row["coverage"] == 1.0
    assert row["agreement"] == 1.0
    assert row["task_count"] == 2


def test_qc_report_missing_dataset_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/embodied-platform/datasets/ds-nope/qc")
    assert response.status_code == 404


def test_trained_ready_gate_passes_when_coverage_and_agreement_met(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-pass", 100)
    # Two annotators, fully covered and near-identical -> coverage 1.0, agreement 1.0.
    _save_annotation(
        client, dataset["id"], "episode-pass",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-a",
    )
    _save_annotation(
        client, dataset["id"], "episode-pass",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-b",
    )

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["trained_ready"] is True

    # Persisted: the dataset listing reflects the gate result.
    listed = client.get("/api/embodied-platform/datasets").json()
    assert listed[0]["trained_ready"] is True
    # Audited.
    audit = client.get("/api/embodied-platform/audit-events").json()
    assert any(e["action"] == "dataset.trained_ready" for e in audit)


def test_trained_ready_gate_409_when_coverage_below_threshold(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-thin", 100)
    # Only 50 of 100 frames labeled -> coverage 0.5 < 0.9.
    _save_annotation(
        client, dataset["id"], "episode-thin",
        [{"start_frame": 0, "end_frame": 50, "skill_id": "grasp"}],
    )

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 409, promote.text
    reasons = promote.json()["detail"]["reasons"]
    assert any("coverage" in r for r in reasons)

    # Gate failure must NOT flip the flag.
    listed = client.get("/api/embodied-platform/datasets").json()
    assert listed[0]["trained_ready"] is False
    audit = client.get("/api/embodied-platform/audit-events").json()
    assert not any(e["action"] == "dataset.trained_ready" for e in audit)


def test_trained_ready_gate_409_when_agreement_below_threshold(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-disagree", 100)
    # Both fully cover (coverage passes) but their single grasp segments barely
    # overlap -> IoU well below 0.7, so the gate must reject on agreement.
    _save_annotation(
        client, dataset["id"], "episode-disagree",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-a",
    )
    _save_annotation(
        client, dataset["id"], "episode-disagree",
        [
            {"start_frame": 0, "end_frame": 20, "skill_id": "grasp"},
            {"start_frame": 20, "end_frame": 100, "skill_id": "place"},
        ],
        assignee="ann-b",
    )

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 409, promote.text
    reasons = promote.json()["detail"]["reasons"]
    assert any("agreement" in r for r in reasons)


def test_trained_ready_gate_uses_worst_annotator_coverage(tmp_path, monkeypatch):
    """When two annotators disagree on coverage, the gate must use the WORST
    (min), not the best — one under-covering annotator should fail the bar.
    This pins the min-across-tasks choice (max/first would let it pass)."""
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-mixed", 100)
    # ann-a fully covers (1.0); ann-b covers only half (0.5). The grasp segments
    # both start at 0 so agreement on the matched pair is high — coverage is the
    # only failing dimension, isolating the min-aggregation behavior.
    _save_annotation(
        client, dataset["id"], "episode-mixed",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-a",
    )
    _save_annotation(
        client, dataset["id"], "episode-mixed",
        [{"start_frame": 0, "end_frame": 50, "skill_id": "grasp"}], assignee="ann-b",
    )

    report = client.get(f"/api/embodied-platform/datasets/{dataset['id']}/qc").json()
    row = next(r for r in report["episodes"] if r["episode_id"] == "episode-mixed")
    assert row["coverage"] == 0.5  # min(1.0, 0.5), not max

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 409, promote.text
    assert any("coverage" in r for r in promote.json()["detail"]["reasons"])


def test_trained_ready_gate_409_when_dataset_has_no_episodes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 409, promote.text


def test_trained_ready_requires_ml_or_admin_role(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)

    forbidden = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_annotator_headers(),
    )
    assert forbidden.status_code == 403


def test_trained_ready_gate_ignores_non_segment_task_types(tmp_path, monkeypatch):
    """QC coverage and inter-annotator agreement must be measured over
    trajectory_segment tasks only. An orthogonal success_check task (no segments)
    must not zero out an otherwise-passing episode and 409 the trained-ready gate."""
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-mixed", 100)
    # Two trajectory_segment annotators -> coverage 1.0, agreement 1.0.
    _save_annotation(
        client, dataset["id"], "episode-mixed",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-a",
    )
    _save_annotation(
        client, dataset["id"], "episode-mixed",
        [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}], assignee="ann-b",
    )
    # An orthogonal success_check task with no segments (API-valid).
    _save_annotation_typed(
        client, dataset["id"], "episode-mixed", [],
        task_type="success_check", assignee="reviewer-a",
    )

    # The QC report must still show the segment-based metrics, not 0.0.
    report = client.get(f"/api/embodied-platform/datasets/{dataset['id']}/qc").json()
    row = next(r for r in report["episodes"] if r["episode_id"] == "episode-mixed")
    assert row["coverage"] == 1.0
    assert row["agreement"] == 1.0
    assert row["passed"] is True
    assert report["passed"] is True

    promote = client.post(
        f"/api/embodied-platform/datasets/{dataset['id']}/trained-ready",
        headers=_ml_headers(),
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["trained_ready"] is True


def test_qc_over_corrupt_label_returns_failing_report_not_500(tmp_path, monkeypatch):
    """Corrupt persisted label data (a non-int/non-dict label) must NOT reach an
    unhandled 500 — QC must defensively skip it and return a (failing) report,
    upholding the 'corrupt state never 500s' contract. The corrupt label drops
    to non-contributing, so coverage falls to 0 and the episode row fails."""
    def _corrupt(state):
        # A non-dict label and a dict label with a non-integer frame: both must
        # be skipped, not crash int()/dict access.
        state["annotation_tasks"][0]["labels"] = [
            "not-a-dict",
            {"start_frame": "oops", "end_frame": 100, "skill_id": "grasp"},
        ]

    client = _corrupt_state_client(tmp_path, monkeypatch, _corrupt)

    response = client.get("/api/embodied-platform/datasets/ds-corrupt/qc")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is False
    row = next(r for r in body["episodes"] if r["episode_id"] == "episode-corrupt")
    # Both labels were unparseable -> no covered frames -> failing coverage.
    assert row["coverage"] == 0.0
    assert row["passed"] is False


@_JSON_FILE_ONLY
def test_qc_over_corrupt_frame_count_returns_failing_report_not_500(tmp_path, monkeypatch):
    """A NaN frame_count on disk (json.load accepts bare NaN by default) must not
    blow up int(); it degrades to 0 -> failing row, never a 500. A bare NaN can
    only exist in the JSON state FILE — jsonb cannot represent it — so this is
    json-mode-only by definition (hence via_state_file + the skipif)."""
    def _corrupt(state):
        state["episodes"][0]["frame_count"] = float("nan")

    client = _corrupt_state_client(tmp_path, monkeypatch, _corrupt, via_state_file=True)

    response = client.get("/api/embodied-platform/datasets/ds-corrupt/qc")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is False
    row = next(r for r in body["episodes"] if r["episode_id"] == "episode-corrupt")
    assert row["frame_count"] == 0
    assert row["passed"] is False


def test_qc_corrupt_data_is_not_masked_as_404(tmp_path, monkeypatch):
    """Corrupt episode/label data must surface as the handled degraded report,
    NOT a misleading 404 'datasets item not found'. The dataset exists, so a 404
    here would mean an over-broad KeyError catch swallowed the corrupt-data
    error. A genuinely-missing dataset still 404s (asserted alongside)."""
    def _corrupt(state):
        state["annotation_tasks"][0]["labels"] = [{"skill_id": "grasp"}]  # missing frames

    client = _corrupt_state_client(tmp_path, monkeypatch, _corrupt)

    present = client.get("/api/embodied-platform/datasets/ds-corrupt/qc")
    assert present.status_code == 200, present.text  # NOT 404

    missing = client.get("/api/embodied-platform/datasets/ds-does-not-exist/qc")
    assert missing.status_code == 404


def test_qc_endpoint_is_bounded_against_pathological_same_skill_flood(tmp_path, monkeypatch):
    """Algorithmic-complexity DoS guard: an episode with two annotation tasks
    each carrying hundreds of *identical* same-skill labels must NOT trigger the
    O(n^3) Hungarian assignment over the whole group.

    Why identical (not consecutive/disjoint) labels: identical labels all score
    IoU 1.0 against each other -> a DENSE all-ones cost matrix, which is the
    Jonker-Volgenant Hungarian's true O(n^3) worst case (long augmenting paths).
    Above MAX_OPTIMAL_GROUP the greedy fallback runs instead, completing in
    ~0.1s; the all-Hungarian path takes ~7s at N=500, so the 2s bound separates
    them with ~20x post-fix headroom (no flakiness) and a 3.5x pre-fix breach."""
    import time

    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-flood", 100)

    # 500 IDENTICAL same-skill labels per task; well past MAX_OPTIMAL_GROUP so
    # the greedy path is exercised, not dense Hungarian.
    flood = [
        {"start_frame": 0, "end_frame": 100, "skill_id": "grasp"} for _ in range(500)
    ]
    _save_annotation(client, dataset["id"], "episode-flood", flood, assignee="ann-a")
    _save_annotation(client, dataset["id"], "episode-flood", flood, assignee="ann-b")

    start = time.perf_counter()
    response = client.get(f"/api/embodied-platform/datasets/{dataset['id']}/qc")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200, response.text
    # Post-fix is ~0.1s; only a regression to the cubic Hungarian path breaches.
    assert elapsed < 2.0, f"QC took {elapsed:.2f}s — compute bound regressed"


def test_qc_endpoint_bounded_against_greedy_product_size_bomb(tmp_path, monkeypatch):
    """Above MAX_OPTIMAL_GROUP the greedy fallback runs — but pre-cap it still
    materialized and sorted the FULL n*m IoU candidate product (9M tuples at
    n=3000; GB-scale transient memory). The per-side MAX_GREEDY_GROUP_LABELS
    prefix cap bounds the product at cap^2 — the scale the flood test above
    already proves fast. The capped agreement value is pinned so the cap is
    observable and deterministic: cap matched IoU-1.0 pairs over the n-wide
    union denominator."""
    import time

    from api.embodied_platform.qc import MAX_GREEDY_GROUP_LABELS

    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode_with_frames(client, dataset["id"], "episode-bomb", 100)

    n = 3000
    bomb = [
        {"start_frame": 0, "end_frame": 100, "skill_id": "grasp"} for _ in range(n)
    ]
    _save_annotation(client, dataset["id"], "episode-bomb", bomb, assignee="ann-a")
    _save_annotation(client, dataset["id"], "episode-bomb", bomb, assignee="ann-b")

    start = time.perf_counter()
    response = client.get(f"/api/embodied-platform/datasets/{dataset['id']}/qc")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200, response.text
    row = next(
        r for r in response.json()["episodes"] if r["episode_id"] == "episode-bomb"
    )
    assert row["agreement"] == pytest.approx(MAX_GREEDY_GROUP_LABELS / n)
    # Generous bound in the established style (see the flood test above):
    # post-fix this runs in well under a second; only the uncapped full-product
    # sort (or a Hungarian regression) breaches it.
    assert elapsed < 4.0, f"QC took {elapsed:.2f}s — greedy product bound regressed"


# --- real LeRobot ingest on POST /imports ------------------------------------


def test_import_runs_ingest_and_materializes_dataset_and_episodes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "lerobot-demo",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "succeeded", job
    # Message records the materialized count and the target dataset name.
    assert "3" in (job["message"] or "")
    assert "lerobot-demo" in (job["message"] or "")

    # The dataset was created on demand...
    datasets = client.get("/api/embodied-platform/datasets").json()
    demo = next(d for d in datasets if d["name"] == "lerobot-demo")
    assert demo["episode_count"] == 3

    # ...and exactly the 3 fixture episodes were materialized with correct frames.
    episodes = client.get("/api/embodied-platform/episodes").json()
    demo_eps = [e for e in episodes if e["dataset_id"] == demo["id"]]
    assert len(demo_eps) == 3
    frames_by_id = {e["episode_id"]: e["frame_count"] for e in demo_eps}
    assert frames_by_id == {
        "episode_000000": 120,
        "episode_000001": 140,
        "episode_000002": 100,
    }


def test_import_is_idempotent_and_dedupes_episodes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {
        "source_uri": LEROBOT_FIXTURE.as_uri(),
        "dataset_name": "lerobot-demo",
        "format": "lerobot",
    }

    first = client.post("/api/embodied-platform/imports", headers=_admin_headers(), json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "succeeded"

    # Re-importing the same root must not duplicate the dataset or its episodes.
    second = client.post("/api/embodied-platform/imports", headers=_admin_headers(), json=body)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "succeeded"

    datasets = [d for d in client.get("/api/embodied-platform/datasets").json() if d["name"] == "lerobot-demo"]
    assert len(datasets) == 1
    assert datasets[0]["episode_count"] == 3

    episodes = [e for e in client.get("/api/embodied-platform/episodes").json() if e["dataset_id"] == datasets[0]["id"]]
    assert len(episodes) == 3


def test_import_failure_records_failed_job_without_corrupting_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    missing_root = (tmp_path / "no_such_lerobot_root").as_uri()
    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": missing_root,
            "dataset_name": "ghost-dataset",
            "format": "lerobot",
        },
    )
    # Convention: 200 with the persisted *failed* job (response_model=ImportJob),
    # so the failure is queryable and audited rather than rolled back.
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "failed", job
    assert job["message"]  # carries the parse error.

    # State must NOT be partially corrupted: no dataset, no episodes created.
    datasets = client.get("/api/embodied-platform/datasets").json()
    assert all(d["name"] != "ghost-dataset" for d in datasets)
    assert client.get("/api/embodied-platform/episodes").json() == []

    # The failed job is queryable in the import list.
    imports = client.get("/api/embodied-platform/imports").json()
    assert any(j["id"] == job["id"] and j["status"] == "failed" for j in imports)


def test_import_with_malformed_meta_fails_without_corrupting_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    # A root that exists but whose meta/info.json is not valid JSON.
    root = tmp_path / "broken_lerobot"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text("{ not json")
    (root / "meta" / "episodes.jsonl").write_text("")

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": root.as_uri(),
            "dataset_name": "broken-dataset",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed", response.text
    assert response.json()["message"]  # carries the parse error.

    datasets = client.get("/api/embodied-platform/datasets").json()
    assert all(d["name"] != "broken-dataset" for d in datasets)
    assert client.get("/api/embodied-platform/episodes").json() == []


def test_import_non_local_scheme_stays_queued_for_external_flow(tmp_path, monkeypatch):
    """ADAPTED from codex's test_import_rejects_non_local_scheme_as_failed_job:
    the console keeps its original POST /imports contract for NON-LOCAL sources —
    the job is recorded as queued and an external worker drives it through the
    PATCH /imports/{id}/status flow (the synchronous parser can only read local
    file:// / plain-path roots, so insta-failing a remote URI would break the
    pre-existing external-ingest lifecycle and its tests). Nothing may be
    materialized at create time for a remote source."""
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": "s3://robot-lake/run-042",
            "dataset_name": "remote-run",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued", job
    # No dataset materialized at create time for a remote source.
    datasets = client.get("/api/embodied-platform/datasets").json()
    assert all(d["name"] != "remote-run" for d in datasets)

    # The external status-PATCH flow still drives the job.
    running = client.patch(
        f"/api/embodied-platform/imports/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "running", "message": "external decoder started"},
    )
    assert running.status_code == 200, running.text
    assert running.json()["status"] == "running"


def test_import_into_existing_dataset_reuses_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Pre-create the dataset by the same name the import targets.
    existing = _create_dataset(client, name="lerobot-demo")

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "lerobot-demo",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded", response.text

    datasets = [d for d in client.get("/api/embodied-platform/datasets").json() if d["name"] == "lerobot-demo"]
    assert len(datasets) == 1
    assert datasets[0]["id"] == existing["id"]  # reused, not duplicated.
    assert datasets[0]["episode_count"] == 3


def test_import_dedupes_on_storage_uri_not_only_name(tmp_path, monkeypatch):
    """POST /datasets enforces storage_uri uniqueness; the import path must not
    bypass it. A dataset already registered at the import's resolved storage_uri
    (under a *different* name) must be reused, never duplicated into a second row
    sharing the same storage_uri."""
    client = _client(tmp_path, monkeypatch)

    # The import resolves the fixture root to this canonical storage_uri.
    resolved_uri = str(LEROBOT_FIXTURE.resolve())
    pre_created = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": "already-here-under-another-name",
            "modality": "vision_language_action",
            "robot_type": "so100",
            "storage_uri": resolved_uri,
            "description": "Pre-existing row at the same storage location.",
        },
    )
    assert pre_created.status_code == 200, pre_created.text

    # Import targets a DIFFERENT name but the SAME underlying storage_uri.
    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "fresh-name",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded", response.text

    datasets = client.get("/api/embodied-platform/datasets").json()
    # Exactly one row may hold this storage_uri (the dedup invariant).
    same_uri = [d for d in datasets if d["storage_uri"] == resolved_uri]
    assert len(same_uri) == 1, same_uri
    # No new "fresh-name" row was created; the existing row was reused.
    assert same_uri[0]["id"] == pre_created.json()["id"]
    assert all(d["name"] != "fresh-name" for d in datasets)


def test_import_storage_uri_reuse_message_names_the_reused_dataset(tmp_path, monkeypatch):
    """When ingest REUSES an existing dataset by storage_uri (under a
    different name), the success message and import.succeeded audit detail must
    name the dataset that actually received the episodes — the reused dataset's
    name — not the never-created dataset_name from the request."""
    client = _client(tmp_path, monkeypatch)

    resolved_uri = str(LEROBOT_FIXTURE.resolve())
    pre_created = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": "orig",
            "modality": "vision_language_action",
            "robot_type": "so100",
            "storage_uri": resolved_uri,
            "description": "Pre-existing row at the import's storage location.",
        },
    )
    assert pre_created.status_code == 200, pre_created.text

    # Import targets a name that does NOT exist; it reuses 'orig' by storage_uri.
    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "brandnew",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "succeeded", response.text
    # Message names the dataset that received the episodes (the reused 'orig').
    assert "orig" in job["message"], job["message"]
    assert "brandnew" not in job["message"], job["message"]

    # 'brandnew' was never created.
    datasets = client.get("/api/embodied-platform/datasets").json()
    assert all(d["name"] != "brandnew" for d in datasets), datasets

    # The import.succeeded audit event also names 'orig', not 'brandnew'.
    audit = client.get("/api/embodied-platform/audit-events").json()
    succeeded = [e for e in audit if e["action"] == "import.succeeded"]
    assert succeeded, audit
    assert "orig" in succeeded[-1]["detail"], succeeded[-1]
    assert "brandnew" not in succeeded[-1]["detail"], succeeded[-1]


def test_import_with_non_finite_fps_is_failed_job_not_500(tmp_path, monkeypatch):
    """meta/info.json fps = Infinity (json.load accepts bare Infinity) must
    record a FAILED import job, never a 500 from int(inf) raising OverflowError
    outside create_import's IngestError catch."""
    client = _no_raise_client(tmp_path, monkeypatch)
    root = tmp_path / "inf_fps_lerobot"
    # json.dumps won't emit Infinity by default; write the raw token directly.
    meta = root / "meta"
    meta.mkdir(parents=True)
    (meta / "info.json").write_text('{"robot_type": "so100", "fps": Infinity}')
    (meta / "episodes.jsonl").write_text('{"episode_index": 0, "length": 120}\n')

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={"source_uri": root.as_uri(), "dataset_name": "inf-fps", "format": "lerobot"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed", response.text
    # No partial dataset materialized from the failed parse.
    assert all(d["name"] != "inf-fps" for d in client.get("/api/embodied-platform/datasets").json())


def test_import_with_nan_fps_is_failed_job_not_500(tmp_path, monkeypatch):
    """Sibling: fps = NaN must also fail cleanly (int(nan) -> ValueError)."""
    client = _no_raise_client(tmp_path, monkeypatch)
    root = tmp_path / "nan_fps_lerobot"
    meta = root / "meta"
    meta.mkdir(parents=True)
    (meta / "info.json").write_text('{"robot_type": "so100", "fps": NaN}')
    (meta / "episodes.jsonl").write_text('{"episode_index": 0, "length": 120}\n')

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={"source_uri": root.as_uri(), "dataset_name": "nan-fps", "format": "lerobot"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed", response.text


def test_import_with_nul_byte_in_source_uri_is_not_500(tmp_path, monkeypatch):
    """A NUL byte in source_uri must not 500 — on EITHER backend. It is rejected
    at the validation boundary (StrictModel refuses NUL in string fields) with a
    clean 422 before anything is persisted: PostgreSQL jsonb cannot store U+0000,
    so letting it reach the state store would 500 the PG backend while JSON-file
    mode silently persisted it. Nothing (no job row) may be left behind."""
    client = _no_raise_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={"source_uri": "/tmp/lerobot\x00root", "dataset_name": "nul-ds", "format": "lerobot"},
    )
    assert response.status_code != 500, response.text
    # Pinned exact status: rejected at the request boundary on both backends.
    assert response.status_code == 422, response.text
    # Rejected before persistence: no import job (failed or otherwise) recorded.
    assert client.get("/api/embodied-platform/imports").json() == []


def test_retry_failed_local_import_reruns_ingest_and_succeeds(tmp_path, monkeypatch):
    """PATCH failed->queued on a LOCAL-source import must actually RE-RUN the
    synchronous ingest, not park the job in a dead-end queued state no worker
    will ever pick up. Once the source root is fixed, the retry materializes
    the dataset/episodes and drives the job to succeeded."""
    import shutil

    client = _client(tmp_path, monkeypatch)

    late_root = tmp_path / "late_lerobot"
    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": late_root.as_uri(),
            "dataset_name": "late-demo",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "failed", job

    # The operator fixes the source, then retries via the documented
    # failed->queued transition.
    shutil.copytree(LEROBOT_FIXTURE, late_root)
    retry = client.patch(
        f"/api/embodied-platform/imports/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "queued", "message": "retry after fixing the root"},
    )
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    assert retried["status"] == "succeeded", retried
    assert "3" in (retried["message"] or "")

    # The ingest really ran: dataset created and episodes materialized.
    datasets = client.get("/api/embodied-platform/datasets").json()
    demo = next(d for d in datasets if d["name"] == "late-demo")
    assert demo["episode_count"] == 3
    episodes = [
        e for e in client.get("/api/embodied-platform/episodes").json()
        if e["dataset_id"] == demo["id"]
    ]
    assert len(episodes) == 3
    # Audited like the create-path ingest.
    audit = client.get("/api/embodied-platform/audit-events").json()
    assert any(e["action"] == "import.succeeded" and e["resource"] == job["id"] for e in audit)


def test_queue_retry_failed_local_import_reruns_ingest(tmp_path, monkeypatch):
    """Regression guard: the unified PATCH /queue/import/{id}/status must
    DELEGATE to the dedicated import retry — failed->queued on a LOCAL source
    re-runs the synchronous ingest and lands on succeeded, instead of parking
    the job in a dead-end queued that no worker picks up."""
    import shutil

    client = _client(tmp_path, monkeypatch)

    late_root = tmp_path / "queue_late_lerobot"
    job = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={"source_uri": late_root.as_uri(), "dataset_name": "queue-late-demo", "format": "lerobot"},
    ).json()
    assert job["status"] == "failed", job

    shutil.copytree(LEROBOT_FIXTURE, late_root)
    retry = client.patch(
        f"/api/embodied-platform/queue/import/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "queued", "message": "retry via the unified queue"},
    )
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    # QueueItem response, but the underlying import really re-ingested.
    assert retried["kind"] == "import"
    assert retried["status"] == "succeeded", retried
    demo = next(
        d for d in client.get("/api/embodied-platform/datasets").json()
        if d["name"] == "queue-late-demo"
    )
    assert demo["episode_count"] == 3


def test_retry_failed_local_import_with_still_bad_source_fails_again(tmp_path, monkeypatch):
    """A retried LOCAL import whose source is STILL broken must come back as a
    failed job carrying the parse error — never stuck queued."""
    client = _client(tmp_path, monkeypatch)

    missing_root = (tmp_path / "still_missing").as_uri()
    job = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": missing_root,
            "dataset_name": "still-broken",
            "format": "lerobot",
        },
    ).json()
    assert job["status"] == "failed", job

    retry = client.patch(
        f"/api/embodied-platform/imports/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "queued", "message": "retry without fixing anything"},
    )
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    assert retried["status"] == "failed", retried
    assert retried["message"]  # carries the parse error detail.
    # Nothing materialized on the failed retry either.
    assert all(d["name"] != "still-broken" for d in client.get("/api/embodied-platform/datasets").json())


def test_retry_failed_nonlocal_import_keeps_external_queued_semantics(tmp_path, monkeypatch):
    """A NON-local (e.g. s3://) failed import retried via failed->queued keeps
    the original external-worker contract: it stays queued for the external
    status-PATCH flow — the synchronous parser cannot read remote roots."""
    client = _client(tmp_path, monkeypatch)

    job = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": "s3://robot-lake/run-099",
            "dataset_name": "remote-retry",
            "format": "lerobot",
        },
    ).json()
    assert job["status"] == "queued", job
    for status in ("running", "failed"):
        r = client.patch(
            f"/api/embodied-platform/imports/{job['id']}/status",
            headers=_admin_headers(),
            json={"status": status, "message": f"external {status}"},
        )
        assert r.status_code == 200, r.text

    retry = client.patch(
        f"/api/embodied-platform/imports/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "queued", "message": "external retry"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued", retry.json()


def test_retry_failed_unsupported_format_import_fails_again_not_stuck_queued(tmp_path, monkeypatch):
    """Retrying a failed local import whose format has no parser must re-fail
    with the clear unsupported-format message (mirroring create), not park the
    job queued forever."""
    client = _client(tmp_path, monkeypatch)

    job = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "rosbag-retry",
            "format": "rosbag",
        },
    ).json()
    assert job["status"] == "failed", job

    retry = client.patch(
        f"/api/embodied-platform/imports/{job['id']}/status",
        headers=_admin_headers(),
        json={"status": "queued", "message": "retry the rosbag"},
    )
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    assert retried["status"] == "failed", retried
    assert "rosbag" in (retried["message"] or "")
    # Still nothing materialized.
    assert client.get("/api/embodied-platform/datasets").json() == []
    assert client.get("/api/embodied-platform/episodes").json() == []


def test_unsupported_import_format_fails_job_without_materializing(tmp_path, monkeypatch):
    """The import `format` field is NOT a silent no-op. Only 'lerobot' has a
    real parser; a non-lerobot format (rosbag/jsonl/...) must FAIL the job with a
    clear message instead of being misparsed as LeRobot. The format check precedes
    the parse, so the side-effect assertion is what encodes the finding: NO dataset
    and NO episodes may be materialized for the rejected format."""
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            # A real LeRobot root, but advertised under a non-lerobot format.
            "source_uri": LEROBOT_FIXTURE.as_uri(),
            "dataset_name": "rosbag-attempt",
            "format": "rosbag",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "failed", job
    assert "rosbag" in (job["message"] or "")

    # The fixture was NOT parsed as LeRobot: no dataset, no episodes materialized.
    assert client.get("/api/embodied-platform/datasets").json() == []
    assert client.get("/api/embodied-platform/episodes").json() == []
