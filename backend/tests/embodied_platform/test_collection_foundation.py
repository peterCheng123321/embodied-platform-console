"""Tests for first-person collection foundation workflow."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


LOGIN_PASSCODE = "pytest-login-passcode"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _headers(role: str = "admin", actor: str = "pytest-admin") -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Role": role,
        "X-Embodied-Actor": actor,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _create_run(client: TestClient) -> dict:
    response = client.post(
        "/api/embodied-platform/collection-runs",
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
        f"/api/embodied-platform/collection-runs/{run_id}/attempts",
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


def test_collection_profile_lists_eight_trial_tasks(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/api/embodied-platform/collection-profiles")

    assert response.status_code == 200, response.text
    profiles = response.json()
    assert [profile["id"] for profile in profiles] == ["first_person_trial_v1"]
    profile = profiles[0]
    assert profile["task_count_required"] == 8
    assert profile["default_required_uploads"] == 6
    assert profile["default_max_attempts"] == 8
    assert len(profile["tasks"]) == 8
    assert {task["mode"] for task in profile["tasks"]} == {"ordinary", "speak_while_doing"}
    assert "missing_required_speech" in [issue["id"] for issue in profile["issue_codes"]]


def test_run_starts_collecting_with_zero_progress(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    run = _create_run(client)
    progress = client.get(f"/api/embodied-platform/collection-runs/{run['id']}/progress").json()

    assert run["status"] == "collecting"
    assert progress["status"] == "collecting"
    assert progress["completed_task_count"] == 0
    assert progress["ready_task_count"] == 0
    assert progress["blocked_task_count"] == 0
    assert len(progress["tasks"]) == 8


def test_six_uploaded_attempts_make_one_task_ready(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    for index in range(1, 7):
        _add_attempt(client, run["id"], "task_01", index)

    attempts = client.get("/api/embodied-platform/collection-attempts")
    assert attempts.status_code == 200, attempts.text
    assert len(attempts.json()) == 6

    progress = client.get(f"/api/embodied-platform/collection-runs/{run['id']}/progress").json()
    task = next(item for item in progress["tasks"] if item["task_id"] == "task_01")
    assert task["uploaded_count"] == 6
    assert task["remaining_attempts"] == 2
    assert task["status"] == "ready_for_review"
    assert progress["ready_task_count"] == 1
    assert progress["status"] == "collecting"


def test_eight_attempts_with_too_few_uploads_blocks_task(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    for index in range(1, 6):
        _add_attempt(client, run["id"], "task_02", index, status="uploaded")
    for index in range(6, 9):
        _add_attempt(client, run["id"], "task_02", index, status="recorded")

    progress = client.get(f"/api/embodied-platform/collection-runs/{run['id']}/progress").json()
    task = next(item for item in progress["tasks"] if item["task_id"] == "task_02")
    assert task["uploaded_count"] == 5
    assert task["attempt_count"] == 8
    assert task["remaining_attempts"] == 0
    assert task["status"] == "blocked"
    assert progress["blocked_task_count"] == 1
    assert progress["status"] == "blocked"


def test_review_accepts_known_issue_codes_and_writes_audit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)
    attempt = _add_attempt(client, run["id"], "task_03", 1)

    response = client.patch(
        f"/api/embodied-platform/collection-attempts/{attempt['id']}/review",
        headers=_headers("reviewer", "reviewer-a"),
        json={
            "decision": "reject",
            "check_results": [
                {"check_id": "speech.required_phrase", "result": "fail", "note": "Missing end phrase"},
                {"check_id": "scene.clutter", "result": "pass", "note": ""},
            ],
            "issue_codes": ["missing_required_speech"],
            "notes": "Retry with clear required wording.",
        },
    )

    assert response.status_code == 200, response.text
    reviewed = response.json()
    assert reviewed["status"] == "rejected"
    assert reviewed["review"]["reviewer"] == "reviewer-a"
    assert reviewed["review"]["decision"] == "reject"
    assert reviewed["review"]["issue_codes"] == ["missing_required_speech"]
    audit_events = client.get("/api/embodied-platform/audit-events").json()
    assert any(event["action"] == "collection.review" and event["resource"] == attempt["id"] for event in audit_events)


def test_unknown_task_and_issue_code_are_rejected(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    bad_task = client.post(
        f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
        headers=_headers("annotator", "operator-a"),
        json={
            "task_id": "task_99",
            "attempt_index": 1,
            "video_uri": "file:///trial/bad.mp4",
            "duration_seconds": 10.0,
            "frame_count": 300,
            "status": "uploaded",
        },
    )
    assert bad_task.status_code == 422

    attempt = _add_attempt(client, run["id"], "task_04", 1)
    bad_issue = client.patch(
        f"/api/embodied-platform/collection-attempts/{attempt['id']}/review",
        headers=_headers("reviewer", "reviewer-a"),
        json={
            "decision": "reject",
            "check_results": [{"check_id": "scene.clutter", "result": "fail", "note": ""}],
            "issue_codes": ["not_a_real_issue"],
            "notes": "",
        },
    )
    assert bad_issue.status_code == 422


def test_collection_attempt_create_rejects_review_decision_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    for review_status in ("accepted", "rejected", "rework"):
        resp = client.post(
            f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
            headers=_headers("annotator", "operator-a"),
            json={
                "task_id": "task_01",
                "attempt_index": 1,
                "video_uri": "file:///trial/task_01/attempt-1.mp4",
                "status": review_status,
            },
        )
        assert resp.status_code == 422, f"status={review_status!r} should be rejected but got {resp.status_code}"


def test_collection_attempt_create_cannot_bypass_review_to_passed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run = _create_run(client)

    for index in range(1, 7):
        resp = client.post(
            f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
            headers=_headers("annotator", "operator-a"),
            json={
                "task_id": "task_01",
                "attempt_index": index,
                "video_uri": f"file:///trial/task_01/attempt-{index}.mp4",
                "status": "accepted",
            },
        )
        assert resp.status_code == 422

    progress = client.get(
        f"/api/embodied-platform/collection-runs/{run['id']}/progress",
    ).json()
    assert progress["status"] != "passed"
