"""Lifecycle-transition tests for the state-machine dead-end fixes.

F16 — collection runs gain a manual termination PATCH (completed/failed) so an
abandoned run no longer sits 'collecting' forever; the unreachable
'not_started' enum value is removed.
F17 — queued/running non-local (s3://) imports are cancellable through the
existing job machine (proven by tests; no new code path).
F19 — annotation tasks gain an explicit status machine
(open -> review -> accepted | rework -> review) instead of an advertised-but-
unimplemented enum.
"""
from __future__ import annotations

from typing import get_args

from fastapi import FastAPI
from fastapi.testclient import TestClient


LOGIN_PASSCODE = "pytest-login-passcode"

API = "/api/embodied-platform"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import register_validation_handlers, router

    app = FastAPI()
    app.include_router(router)
    register_validation_handlers(app)
    return TestClient(app)


def _headers(role: str = "admin", actor: str = "pytest-admin") -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Role": role,
        "X-Embodied-Actor": actor,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _audit_events(client: TestClient) -> list[dict]:
    response = client.get(f"{API}/audit-events")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# F16 — collection-run termination
# ---------------------------------------------------------------------------


def _create_run(client: TestClient) -> dict:
    response = client.post(
        f"{API}/collection-runs",
        headers=_headers("admin"),
        json={
            "profile_id": "first_person_trial_v1",
            "subject_id": "operator-a",
            "assignee": "operator-a",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _add_attempt(client: TestClient, run_id: str, task_id: str, attempt_index: int, status: str = "uploaded") -> dict:
    response = client.post(
        f"{API}/collection-runs/{run_id}/attempts",
        headers=_headers("annotator", "operator-a"),
        json={
            "task_id": task_id,
            "attempt_index": attempt_index,
            "video_uri": f"file:///trial/{task_id}/attempt-{attempt_index}.mp4",
            "duration_seconds": 12.5,
            "frame_count": 375,
            "status": status,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _force_run_status(run_id: str, status: str) -> None:
    """Seed a derived run status through the public repository surface.

    Run-level 'ready_for_review'/'passed' require all 8 profile tasks at quota
    (48+ API calls); seeding through ``get_repository().mutate`` keeps the test
    fast and backend-agnostic (same idiom as test_hardening's corrupt-state
    seeding)."""
    from api.embodied_platform.repository import get_repository

    def _mutate(state: dict) -> None:
        run = next(row for row in state["collection_runs"] if row["id"] == run_id)
        run["status"] = status

    get_repository().mutate(_mutate)


def test_collecting_run_terminates_completed_with_reason_and_audit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("reviewer", "reviewer-a"),
        json={"status": "completed", "reason": "quota met out of band"},
    )

    assert response.status_code == 200, response.text
    terminated = response.json()
    assert terminated["status"] == "completed"
    assert terminated["updated_at"] >= run["updated_at"]
    events = _audit_events(client)
    event = next(e for e in events if e["action"] == "collection.run.completed")
    assert event["resource"] == run["id"]
    assert event["detail"] == "quota met out of band"
    assert event["actor"] == "reviewer-a"
    assert event["role"] == "reviewer"


def test_collecting_run_terminates_failed_without_reason(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "failed"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    events = _audit_events(client)
    event = next(e for e in events if e["action"] == "collection.run.failed")
    assert event["resource"] == run["id"]
    assert event["detail"] is None


def test_blocked_run_reached_via_api_can_be_failed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    # Exhaust task_02's 8 attempts with only 5 uploads -> task (and run) blocked.
    for index in range(1, 6):
        _add_attempt(client, run["id"], "task_02", index, status="uploaded")
    for index in range(6, 9):
        _add_attempt(client, run["id"], "task_02", index, status="deleted")
    runs = client.get(f"{API}/collection-runs").json()
    assert next(r for r in runs if r["id"] == run["id"])["status"] == "blocked"

    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "failed", "reason": "attempt budget exhausted"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"


def test_ready_for_review_run_can_be_completed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    _force_run_status(run["id"], "ready_for_review")

    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("reviewer", "reviewer-a"),
        json={"status": "completed", "reason": "review done offline"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"


def test_passed_run_rejects_termination_409(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    _force_run_status(run["id"], "passed")

    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "failed"},
    )

    assert response.status_code == 409, response.text


def test_terminated_run_is_immutable(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    completed = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text

    for target in ("completed", "failed"):
        again = client.patch(
            f"{API}/collection-runs/{run['id']}/status",
            headers=_headers("admin"),
            json={"status": target},
        )
        assert again.status_code == 409, again.text


def test_run_termination_unknown_or_nonsettable_status_is_422(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    # Derived statuses are not settable; unknown values are rejected the same way.
    for status in ("collecting", "ready_for_review", "passed", "blocked", "not_started", "bogus"):
        response = client.patch(
            f"{API}/collection-runs/{run['id']}/status",
            headers=_headers("admin"),
            json={"status": status},
        )
        assert response.status_code == 422, f"{status}: {response.text}"

    too_long = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "failed", "reason": "x" * 501},
    )
    assert too_long.status_code == 422, too_long.text


def test_run_termination_requires_annotation_role_group(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    # ml_engineer is a valid write role but not in the collection (annotation)
    # role group — same group as the other collection writes.
    response = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("ml_engineer", "pytest-ml"),
        json={"status": "completed"},
    )

    assert response.status_code == 403, response.text
    assert all(e["action"] != "collection.run.completed" for e in _audit_events(client))


def test_run_termination_unknown_run_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.patch(
        f"{API}/collection-runs/crun_missing/status",
        headers=_headers("admin"),
        json={"status": "failed"},
    )

    assert response.status_code == 404, response.text


def test_terminated_run_rejects_new_attempts_and_reviews(tmp_path, monkeypatch):
    """Attempt/review writes recompute the run status from progress; on a
    manually-terminated run they must 409 instead of silently resurrecting it
    back to a derived status (which would reopen the F16 dead end)."""
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    attempt = _add_attempt(client, run["id"], "task_01", 1)
    failed = client.patch(
        f"{API}/collection-runs/{run['id']}/status",
        headers=_headers("admin"),
        json={"status": "failed", "reason": "abandoned"},
    )
    assert failed.status_code == 200, failed.text

    new_attempt = client.post(
        f"{API}/collection-runs/{run['id']}/attempts",
        headers=_headers("annotator", "operator-a"),
        json={
            "task_id": "task_01",
            "attempt_index": 2,
            "video_uri": "file:///trial/task_01/attempt-2.mp4",
            "duration_seconds": 12.5,
            "frame_count": 375,
            "status": "uploaded",
        },
    )
    assert new_attempt.status_code == 409, new_attempt.text

    review = client.patch(
        f"{API}/collection-attempts/{attempt['id']}/review",
        headers=_headers("reviewer", "reviewer-a"),
        json={"decision": "accept", "check_results": [], "issue_codes": [], "notes": ""},
    )
    assert review.status_code == 409, review.text

    # The terminal status survived both rejected writes.
    runs = client.get(f"{API}/collection-runs").json()
    assert next(r for r in runs if r["id"] == run["id"])["status"] == "failed"


def test_collection_run_status_enum_drops_unreachable_not_started():
    """No code path ever produced 'not_started' (runs are created 'collecting'
    and every other status is derived or set by the termination PATCH), and no
    fixture/demo state carries it — so it is removed, not kept as legacy."""
    from api.embodied_platform.schema import CollectionRunStatus

    values = set(get_args(CollectionRunStatus))
    assert "not_started" not in values
    assert {"collecting", "ready_for_review", "passed", "completed", "failed", "blocked"} == values


# ---------------------------------------------------------------------------
# F17 — import cancel (existing job machine; proven, not re-implemented)
# ---------------------------------------------------------------------------


def _create_s3_import(client: TestClient) -> dict:
    response = client.post(
        f"{API}/imports",
        headers=_headers("admin"),
        json={
            "source_uri": "s3://robot-lake/run-042",
            "dataset_name": "remote-run",
            "format": "lerobot",
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued", job
    return job


def test_queued_s3_import_can_be_cancelled_with_audit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job = _create_s3_import(client)

    response = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("data_manager", "pytest-dm"),
        json={"status": "cancelled", "message": "source bucket decommissioned"},
    )

    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["message"] == "source bucket decommissioned"
    events = _audit_events(client)
    event = next(e for e in events if e["action"] == "import.status" and e["resource"] == job["id"])
    assert event["detail"] == "cancelled"


def test_running_s3_import_can_be_cancelled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job = _create_s3_import(client)
    running = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("admin"),
        json={"status": "running", "message": "external decoder started"},
    )
    assert running.status_code == 200, running.text

    response = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("admin"),
        json={"status": "cancelled", "message": "operator abort"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"


def test_cancelled_import_rejects_non_requeue_transitions(tmp_path, monkeypatch):
    """Job machine: cancelled may only go back to queued (re-queue); any other
    target is a 409."""
    client = _client(tmp_path, monkeypatch)
    job = _create_s3_import(client)
    cancelled = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("admin"),
        json={"status": "cancelled", "message": None},
    )
    assert cancelled.status_code == 200, cancelled.text

    for target in ("running", "succeeded", "failed"):
        response = client.patch(
            f"{API}/imports/{job['id']}/status",
            headers=_headers("admin"),
            json={"status": target},
        )
        assert response.status_code == 409, f"{target}: {response.text}"

    # Re-queue stays allowed for the external flow.
    requeued = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("admin"),
        json={"status": "queued", "message": "retry via external worker"},
    )
    assert requeued.status_code == 200, requeued.text
    assert requeued.json()["status"] == "queued"


def test_import_cancel_requires_data_role_group(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job = _create_s3_import(client)

    response = client.patch(
        f"{API}/imports/{job['id']}/status",
        headers=_headers("annotator", "labeler-a"),
        json={"status": "cancelled"},
    )

    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# F19 — annotation task status transitions
# ---------------------------------------------------------------------------


def _create_annotation_task(client: TestClient, status: str = "open") -> dict:
    dataset = client.post(
        f"{API}/datasets",
        headers=_headers("admin"),
        json={
            "name": "warehouse-pick-v1",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/warehouse-pick-v1",
            "description": None,
        },
    )
    assert dataset.status_code == 200, dataset.text
    episode = client.post(
        f"{API}/episodes",
        headers=_headers("admin"),
        json={
            "dataset_id": dataset.json()["id"],
            "episode_id": "episode-000042",
            "robot_cell": "warehouse-a",
            "frame_count": 240,
        },
    )
    assert episode.status_code == 200, episode.text
    task = client.post(
        f"{API}/annotation-tasks",
        headers=_headers("annotator", "labeler-a"),
        json={
            "dataset_id": dataset.json()["id"],
            "episode_id": "episode-000042",
            "task_type": "trajectory_segment",
            "assignee": "labeler-a",
            "labels": [{"start_frame": 0, "end_frame": 64, "skill_id": "approach"}],
            "status": status,
        },
    )
    assert task.status_code == 200, task.text
    return task.json()


def _patch_annotation_status(client: TestClient, task_id: str, status: str, role: str = "reviewer", actor: str = "reviewer-a"):
    return client.patch(
        f"{API}/annotation-tasks/{task_id}/status",
        headers=_headers(role, actor),
        json={"status": status},
    )


def test_annotation_review_loop_open_review_rework_review_accepted(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task = _create_annotation_task(client)
    assert task["status"] == "open"

    for target in ("review", "rework", "review", "accepted"):
        response = _patch_annotation_status(client, task["id"], target)
        assert response.status_code == 200, f"{target}: {response.text}"
        body = response.json()
        assert body["status"] == target
        assert body["updated_at"] >= task["updated_at"]

    listed = client.get(f"{API}/annotation-tasks").json()
    assert next(t for t in listed if t["id"] == task["id"])["status"] == "accepted"

    audit_details = [
        e["detail"]
        for e in _audit_events(client)
        if e["action"] == "annotation.status" and e["resource"] == task["id"]
    ]
    assert audit_details == ["review", "rework", "review", "accepted"]


def test_annotation_invalid_transitions_are_409(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task = _create_annotation_task(client)

    # open may only go to review.
    for target in ("accepted", "rework", "open"):
        response = _patch_annotation_status(client, task["id"], target)
        assert response.status_code == 409, f"open->{target}: {response.text}"

    moved = _patch_annotation_status(client, task["id"], "review")
    assert moved.status_code == 200, moved.text
    # review may not loop to itself or reopen.
    for target in ("review", "open"):
        response = _patch_annotation_status(client, task["id"], target)
        assert response.status_code == 409, f"review->{target}: {response.text}"


def test_accepted_annotation_task_is_immutable(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task = _create_annotation_task(client)
    for target in ("review", "accepted"):
        response = _patch_annotation_status(client, task["id"], target)
        assert response.status_code == 200, response.text

    for target in ("open", "review", "rework", "accepted"):
        response = _patch_annotation_status(client, task["id"], target)
        assert response.status_code == 409, f"accepted->{target}: {response.text}"


def test_annotation_status_unknown_value_is_422(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task = _create_annotation_task(client)

    response = _patch_annotation_status(client, task["id"], "bogus")

    assert response.status_code == 422, response.text


def test_annotation_status_requires_annotation_role_group(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task = _create_annotation_task(client)

    response = _patch_annotation_status(client, task["id"], "review", role="ml_engineer", actor="pytest-ml")

    assert response.status_code == 403, response.text
    assert all(e["action"] != "annotation.status" for e in _audit_events(client))


def test_annotation_status_unknown_task_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = _patch_annotation_status(client, "ann_missing", "review")

    assert response.status_code == 404, response.text
